FROM postgres:18-alpine@sha256:9a8afca54e7861fd90fab5fdf4c42477a6b1cb7d293595148e674e0a3181de15

# The official entrypoint supports an already-unprivileged process. Removing
# gosu eliminates an unused privilege-drop binary and its vulnerable Go runtime.
RUN rm -f /usr/local/bin/gosu
USER postgres
