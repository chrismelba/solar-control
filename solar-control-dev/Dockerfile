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
    mkdir -p /etc/nginx/http.d && \
    mkdir -p /tmp/nginx

# Set permissions
RUN \
    chown -R nginx:nginx /run/nginx && \
    chown -R nginx:nginx /tmp/nginx && \
    chmod -R 755 /etc/nginx && \
    chmod -R 755 /usr/bin/static && \
    chmod -R 755 /run/nginx && \
    chmod -R 755 /tmp/nginx

# Copy root filesystem
COPY rootfs /

# Make scripts executable
RUN \
    chmod +x /usr/bin/my_program.py && \
    chmod a+x /etc/services.d/solar-control/run && \
    chmod a+x /etc/services.d/solar-control/finish

# Launch nginx
CMD [ "nginx", "-g", "daemon off;" ]