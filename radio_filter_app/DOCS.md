# Music Assistant with Radio Filter

A custom Home Assistant OS App based on **Music Assistant server 2.10.6** with the Radio Filter plugin installed. This is a **replacement server app**, not a patch to your existing official Music Assistant app.

1. Make a full Home Assistant backup including your Music Assistant app. Keep a separate copy of your MA settings and database before changing apps.
2. Stop the official Music Assistant app before starting this app. Both run their own Music Assistant server and should not run simultaneously on the same host/network port.
3. In Home Assistant go to **Settings → Apps → App store → ⋮ → Repositories**. Add `https://github.com/3115a083/ma---Radio-Filter`.
4. Find **Music Assistant with Radio Filter** in the store and install it. Home Assistant may build the application locally from the included Dockerfile, requiring enough disk space and RAM.
5. Start the app, choose **Open Web UI**, and configure Music Assistant. In its own **Settings → Plugins → Add plugin**, choose **Radio Filter** and edit rules in the native GUI fields. If an older MA integration points to the original server, reconfigure its connection to the new server.
6. To revert, stop this app and start the official Music Assistant app. Restore its previous backup if required.

**Note:** App data is isolated by the Home Assistant Supervisor. Installing the custom app does not automatically transfer the original app's database. The standard Music Assistant backup/restore mechanisms and Home Assistant backup coverage may differ across releases; do not assume an automatic migration.

The Dockerfile uses the official version-tagged Music Assistant image; its upstream dependencies and binary components retain their own security/update lifecycle. This app is experimental and has not been tested inside Home Assistant OS yet.
