# The MCP Apps sandbox proxy. One static page, deliberately.
#
# It must be served from an origin distinct from the host app — that
# separation is what contains the View, per SEP-1865. A separate container on
# a separate port satisfies it.
FROM nginx:alpine
COPY sandbox/index.html /usr/share/nginx/html/index.html
EXPOSE 80
