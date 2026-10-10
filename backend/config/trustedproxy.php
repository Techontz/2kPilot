<?php

/*
| Proxies whose X-Forwarded-For Laravel believes (read by the framework's
| TrustProxies middleware). The dashboard reaches Laravel through the Next.js
| server, so that server's address must be listed: 127.0.0.1 when both run on
| one machine, the Docker network (e.g. 172.16.0.0/12) under docker compose.
| Comma-separated IPs or CIDR ranges. Never "*": any client could then pick
| its own IP and dodge the per-IP limits.
|
| The edge proxy (nginx) must OVERWRITE X-Forwarded-For with the real client
| address (proxy_set_header X-Forwarded-For $remote_addr;), not append to a
| value the client sent. See docs/DEPLOYMENT.md.
*/

return [
    'proxies' => env('TRUSTED_PROXIES', '127.0.0.1,::1'),
];
