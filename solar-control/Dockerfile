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
    python3 -m venv /opt/venv \
    && \
    /opt/venv/bin/pip install --no-cache-dir flask requests pytz paho-mqtt

ENV PATH="/opt/venv/bin:$PATH"

# Create required directories
RUN \
    mkdir -p /run/nginx && \
    mkdir -p /usr/bin/static/css /usr/bin/static/js && \
    mkdir -p /data && \
    mkdir -p /data/nginx/logs /data/nginx/tmp/client_body && \
    mkdir -p /etc/nginx/http.d && \
    mkdir -p /var/lib/nginx && \
    mkdir -p /var/lib/nginx/logs

# Set permissions
RUN \
    chown -R root:root /data && \
    chmod -R 755 /data && \
    chmod -R 755 /data/nginx && \
    chmod -R 755 /etc/nginx && \
    chmod -R 755 /usr/bin/static && \
    chown -R root:root /var/lib/nginx && \
    chmod -R 755 /var/lib/nginx && \
    chmod -R 755 /var/lib/nginx/logs && \
    chmod -R 755 /run/nginx

# Copy root filesystem
COPY rootfs /

# Make scripts executable
RUN \
    chmod +x /usr/bin/my_program.py && \
    chmod a+x /etc/services.d/solar-control/run && \
    chmod a+x /etc/services.d/solar-control/finish && \
    chmod a+x /etc/services.d/nginx/run && \
    chmod a+x /etc/services.d/nginx/finish