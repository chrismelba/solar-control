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
    && \
    curl -sSLf -o /usr/bin/tempio \
    "https://github.com/home-assistant/tempio/releases/download/${TEMPIO_VERSION}/tempio_${BUILD_ARCH}" && \
    chmod a+x /usr/bin/tempio && \
    pip3 install flask requests pytz

# Create static directory
RUN mkdir -p /usr/bin/static/css /usr/bin/static/js

# Create data directory for persistent storage
RUN mkdir -p /data && \
    chmod 755 /data

# Copy root filesystem
COPY rootfs /

# Make the Python script executable
RUN chmod +x /usr/bin/my_program && \
    chmod a+x /etc/services.d/solar-control/run && \
    chmod a+x /etc/services.d/solar-control/finish && \
    chmod -R 755 /usr/bin/static

