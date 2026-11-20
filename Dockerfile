FROM nginxinc/nginx-unprivileged:1.28-alpine

USER root
RUN apk add --no-cache curl jq \
 && mkdir -p /var/lib/login-skin/logos /logos-custom \
 && chown -R 101:101 /var/lib/login-skin

COPY docker/default.conf.template /etc/nginx/templates/default.conf.template
COPY docker/proxy.inc             /etc/nginx/login-skin-proxy.inc
COPY docker/collect-logos.sh      /usr/local/bin/collect-logos
COPY docker/40-login-skin.sh      /docker-entrypoint.d/40-login-skin.sh
COPY skin/                        /usr/share/nginx/html/login-skin/
RUN chmod 755 /usr/local/bin/collect-logos /docker-entrypoint.d/40-login-skin.sh \
 && rm -f /etc/nginx/conf.d/default.conf

# where GitLab (Workhorse, or its nginx) is reachable from this container - set this
ENV GITLAB_UPSTREAM=http://127.0.0.1:8181 \
    SKIN_CONCEPT=random \
    SKIN_LAYOUTS=scatter,orbit,corners \
    SKIN_COUNT=15-20 \
    SKIN_GRAIN=0.38 \
    LOGOS_DIR=/var/lib/login-skin/logos \
    LOGOS_CUSTOM_DIR=/logos-custom \
    LOGO_VISIBILITY=public \
    LOGO_MAX=60 \
    LOGO_REFRESH_SECONDS=21600

USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD curl -fsS http://127.0.0.1:8080/-/login-skin/healthz || exit 1
