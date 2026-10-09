# Highscore refresh trigger (AWS)

GitHub's `schedule:` cron is throttled on free repos (runs land hours apart).
This stack checks the highscores "last update" age 4 times an hour and
dispatches `track-exp.yml` as soon as the age drops, meaning the highscores
just refreshed. The cron in the workflow stays as a fallback.

```
EventBridge Scheduler (4x/hour)
  -> Lambda tibia-highscore-trigger
       reads highscore_age from TibiaData
       compares with SSM /tibia/last-highscore-age
       age dropped? -> POST workflow_dispatch to GitHub
```

Cost: about 2,900 Lambda runs and 2,900 schedule triggers a month, 128MB
on arm64. That is under 1% of the always-free Lambda and Scheduler tiers,
shared with your other functions. Logs are kept for 7 days.

## Security model

| Secret / power | Who holds it |
|---|---|
| GitHub token | You create it and store it as an SSM SecureString. Only the Lambda can read it. The deployer role is explicitly denied. |
| Deploy rights | `claude-deployer` role, limited to `tibia-*` resources, used through 30 minute STS sessions. |
| Privilege escalation | Any role the deployer creates must carry the `tibia-boundary` permissions boundary, which caps it at logs, `/tibia/*` parameters and invoking `tibia-*` functions. The deployer cannot remove the boundary or attach managed policies. |

## One time setup (owner, in AWS CloudShell)

Use the region you want this to run in.

**1. GitHub token.** Create a fine grained PAT at
<https://github.com/settings/personal-access-tokens/new>:
repository access *Only select repositories* -> this repo,
permission *Actions: Read and write*, nothing else. Set an expiry and
a reminder to rotate it.

**2. Store it without echoing it into shell history:**

```bash
read -rs GH_PAT && aws ssm put-parameter --name /tibia/github-token \
  --type SecureString --value "$GH_PAT" && unset GH_PAT
```

**3. Create the deployer role:**

```bash
git clone https://github.com/ruslex1234/tibia-target-exp-tracker.git
cd tibia-target-exp-tracker && git checkout claude/aws-highscore-trigger
aws cloudformation deploy --stack-name claude-deployer-bootstrap \
  --template-file aws/bootstrap-deployer.yaml --capabilities CAPABILITY_NAMED_IAM
```

**4. Issue a 30 minute session:**

```bash
aws sts assume-role --duration-seconds 1800 --role-session-name claude \
  --role-arn "$(aws iam get-role --role-name claude-deployer --query Role.Arn --output text)" \
  --query Credentials --output json
```

The output expires on its own after 30 minutes. Every action taken with it
appears in CloudTrail under session name `claude`.

## Deploy (with the deployer session)

```bash
aws cloudformation deploy --stack-name tibia-highscore-trigger \
  --template-file aws/highscore-trigger.yaml --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides BoundaryPolicyArn=arn:aws:iam::<ACCOUNT_ID>:policy/tibia-boundary
aws lambda invoke --function-name tibia-highscore-trigger /dev/stdout
```

## Tuning

* Faster reaction: `ScheduleExpression=cron(*/5 * * * ? *)` (about 8,800 runs a month, still free).
* Different world: `World=<name>`.
* Remove everything: delete stack `tibia-highscore-trigger`, then `claude-deployer-bootstrap`,
  then the `/tibia/github-token` parameter.
