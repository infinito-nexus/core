# Administration

## create user via POST

```bash
curl -X POST https://your-pds-domain/xrpc/com.atproto.server.createAccount \
  --user "admin:$admin-password" 
  -H "Content-Type: application/json" \
  -d '{
        "email": "user@example.com",
        "handle": "username",
        "password": "securepassword123",
        "inviteCode": "optional-invite-code"
      }'
```

## Use pdsadmin

compose exec -it pds pdsadmin

compose exec -it pds pdsadmin account create-invite-code

## Debugging

- Websocket: [piehost.com/websocket-tester](https://piehost.com/websocket-tester)
- Instance: [bsky-debug.app](https://bsky-debug.app)

Initial setup keine top level domain
