# Connect Gmail

Command Center reads your Gmail with its own Google OAuth client, so nothing is shared with anyone
else. The scope is `gmail.readonly`: it can read mail and cannot send, delete or change anything.
The app never reads message bodies; it shows who wrote, the subject and Gmail's short snippet.

## Create the client (about 5 minutes, once)
1. Open https://console.cloud.google.com/ and create a project (any name, e.g. "Command Center").
2. APIs & Services > Library > search "Gmail API" > Enable.
3. APIs & Services > OAuth consent screen (Google Auth platform > Branding/Audience in the newer UI):
   - User type: **External**. Fill in the app name and your email.
   - Leave the publishing status as **Testing**.
   - Under Test users, **add your own Gmail address**. Without this Google refuses the sign-in.
4. APIs & Services > Credentials > Create credentials > OAuth client ID > Application type
   **Desktop app**. Download the JSON file (or copy its contents).
5. In Command Center, open Settings > Gmail and paste the whole file into the "Google credentials" box, then
   press Connect. Your browser opens; choose your account and allow read-only access. Google may warn
   that the app is unverified: that is expected for your own client, choose Continue.

What you paste is stored only on this computer, never in the project folder or any file you commit,
and Command Center never shows it again after you save it.

## Reconnect every 7 days
While the consent screen is in Testing, Google expires the sign-in after 7 days (decision 0003).
Gmail then shows **Reconnect**; press it and sign in again. Publishing the app would lift the limit
but requires Google's verification, which a personal tool does not need.

## Troubleshooting
- "Sign-in timed out": the browser sign-in must finish within 3 minutes. Press Connect again.
- "That is not a Google OAuth desktop client file": the client was created as a Web application.
  Create a **Desktop app** client instead.
- "check the Gmail API is enabled": repeat step 2 in the same project as the client.
- Access blocked / error 403 access_denied: your address is not in the test users list (step 3).
