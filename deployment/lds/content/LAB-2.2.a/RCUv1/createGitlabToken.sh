#!/bin/bash

GITLAB_USER="root"
TOKEN_NAME="token123"
GENERATED_TOKEN="token-123123-123412345" 

sudo gitlab-rails runner "
  user = User.find_by_username('$GITLAB_USER');
  token = user.personal_access_tokens.create(
    scopes: [:api],
    name: '$TOKEN_NAME',
    expires_at: 365.days.from_now
  );
  token.set_token('$GENERATED_TOKEN');
  token.save!;
  puts token.token;
  Feature.disable(:paneled_view)
"
