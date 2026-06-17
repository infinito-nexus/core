# Cloudflare API Token for Ansible (`API.cloudflare.api_token`)

This document explains how to generate and use a Cloudflare API Token for DNS automation and certificate operations in Ansible (e.g., with Certbot).

## Purpose

The `API.cloudflare.api_token` value (declared in `group_vars/all/18_api.yml`, read via `lookup('api', 'cloudflare.api_token')`) must contain a valid Cloudflare API Token.  
This token is used for all DNS operations and ACME (SSL/TLS certificate) challenges that require access to your Cloudflare-managed domains.

**Never commit your API token to a public repository. Always keep it secure!**

---

## How to Create a Cloudflare API Token

### 1. Log In to Cloudflare

- Go to: [https://dash.cloudflare.com/](https://dash.cloudflare.com/) and log in.

### 2. Open the API Tokens Page

- Click your profile icon (top right) → **My Profile**
- In the sidebar, choose **API Tokens**  
  Or use this direct link: [https://dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)

### 3. Click **Create Token**

### 4. Select **Custom Token**

- Give your token a descriptive name (e.g., `Ansible Certbot Automation`).

### 5. Set Permissions

Add the following permissions:

| Category | Permission   | Access   |
| -------- | ------------ | -------- |
| Zone     | Zone         | Read     |
| Zone     | DNS          | Edit     |
| Zone     | Cache Purge  | Purge    |

- These permissions are required for DNS record management, CAA/SPF/DKIM handling, cache purging, and certificate provisioning.

### 6. Zone Resources

- **Zone Resources:** Set to `Include → All zones`  
  (Or restrict to specific zones as needed for your environment.)

### 7. Create and Save the Token

- Click **Continue to summary** and then **Create Token**.
- Copy the API Token. **It will only be shown once!**

---

## Using the Token in Ansible

Set the token in your Ansible inventory or secrets file:

```yaml
API:
  cloudflare:
    api_token: "cf_your_generated_token_here"
