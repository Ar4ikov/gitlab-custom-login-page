# shared proxy settings (included by every proxied location)
proxy_http_version 1.1;
proxy_set_header Host              $http_host;
proxy_set_header X-Real-IP         $skin_real_ip;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $skin_fwd_proto;
proxy_set_header X-Forwarded-Host  $http_host;
proxy_set_header X-Forwarded-Port  $skin_fwd_port;
proxy_set_header X-Forwarded-Ssl   $skin_fwd_ssl;
proxy_set_header Upgrade           $http_upgrade;
proxy_set_header Connection        $skin_connection;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
