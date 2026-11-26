# Builds the phone app (Android APK) on the VPS itself, the same way the GitHub build did on Ubuntu:
# Java 17, Node 22, Rust with the two Android targets, the Android SDK and NDK. Used by build-apk.sh.
FROM eclipse-temurin:17-jdk-jammy

ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    NDK_VERSION=27.2.12479018 \
    RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo
ENV NDK_HOME=$ANDROID_HOME/ndk/$NDK_VERSION \
    PATH=/opt/cargo/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip git ca-certificates build-essential \
      python3 file xz-utils \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p $ANDROID_HOME/cmdline-tools \
 && curl -fsSL -o /tmp/tools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
 && unzip -q /tmp/tools.zip -d $ANDROID_HOME/cmdline-tools \
 && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
 && rm /tmp/tools.zip \
 && yes | sdkmanager --licenses >/dev/null \
 && sdkmanager "platform-tools" "ndk;$NDK_VERSION" "build-tools;35.0.0" "platforms;android-35" \
 && (sdkmanager "platforms;android-37" || echo "android-37 will be fetched by Gradle")

RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable \
 && rustup target add aarch64-linux-android armv7-linux-androideabi

WORKDIR /src
