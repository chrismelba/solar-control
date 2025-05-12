# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install required packages
RUN \
    apk add --no-cache \
        curl \
        python3 \
        py3-pip \
        nginx \
    && \
    pip3 install flask requests pytz

# Create required directories
RUN \
    mkdir -p /run/nginx && \
    mkdir -p /usr/bin/static/css /usr/bin/static/js && \
    mkdir -p /data && \
    mkdir -p /data/nginx/logs /data/nginx/tmp/client_body && \
    mkdir -p /etc/nginx/http.d

# Set permissions
RUN \
    chown -R root:root /data && \
    chmod -R 755 /data && \
    chmod -R 755 /data/nginx && \
    chmod -R 755 /etc/nginx && \
    chmod -R 755 /usr/bin/static

# Copy root filesystem
COPY rootfs /

# Make scripts executable
RUN \
    chmod +x /usr/bin/my_program && \
    chmod a+x /etc/services.d/solar-control/run && \
    chmod a+x /etc/services.d/solar-control/finish

# Launch nginx with debug options
CMD [ "nginx", "-g", "daemon off;error_log /dev/stdout debug;" ]