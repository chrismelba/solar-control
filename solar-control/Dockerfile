# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Execute during the build of the image
ARG TEMPIO_VERSION BUILD_ARCH
RUN \
    apk add --no-cache \
        curl \
        python3 \
        py3-pip \
        nginx \
    && \
    curl -sSLf -o /usr/bin/tempio \
    "https://github.com/home-assistant/tempio/releases/download/${TEMPIO_VERSION}/tempio_${BUILD_ARCH}" && \
    chmod a+x /usr/bin/tempio && \
    pip3 install flask requests pytz

# Create static directory
RUN mkdir -p /usr/bin/static/css /usr/bin/static/js

# Create data directory for persistent storage and set permissions
RUN mkdir -p /data && \
    chown -R root:root /data && \
    chmod -R 755 /data

# Create your custom Nginx directories under /data for logs and temporary files
RUN mkdir -p /data/nginx/logs /data/nginx/tmp/client_body && \
    chmod -R 755 /data/nginx

# Create Nginx configuration directories (if needed from your setup)
RUN mkdir -p /etc/nginx/http.d && \
    chmod -R 755 /etc/nginx

# Copy root filesystem, which now contains your custom nginx.conf and server config
COPY rootfs /

# Make the Python script executable
RUN chmod +x /usr/bin/my_program && \
    chmod a+x /etc/services.d/solar-control/run && \
    chmod a+x /etc/services.d/solar-control/finish && \
    chmod -R 755 /usr/bin/static

# Add nginx and create the run folder for nginx
RUN \
  apk --no-cache add \
    nginx \
  \
  && mkdir -p /run/nginx

# Copy our conf into the nginx http.d folder
COPY rootfs/etc/nginx/http.d/default.conf /etc/nginx/http.d/

# Launch nginx with debug options
CMD [ "nginx", "-g", "daemon off;error_log /dev/stdout debug;" ]