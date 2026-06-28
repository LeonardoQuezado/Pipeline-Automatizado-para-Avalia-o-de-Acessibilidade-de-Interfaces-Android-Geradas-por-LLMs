FROM python:3.11-slim

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    openjdk-21-jdk \
    wget \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Android SDK ───────────────────────────────────────────────────────────────
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH=${PATH}:${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin:${ANDROID_SDK_ROOT}/platform-tools

RUN mkdir -p ${ANDROID_SDK_ROOT}/cmdline-tools && \
    cd ${ANDROID_SDK_ROOT}/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-9477386_latest.zip && \
    unzip commandlinetools-linux-9477386_latest.zip && \
    mv cmdline-tools latest && \
    rm commandlinetools-linux-9477386_latest.zip

RUN yes | sdkmanager --licenses && \
    sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"

# ── Gradle wrapper files ──────────────────────────────────────────────────────
# Run `gradle wrapper` once in a throwaway project to get the canonical
# gradle-wrapper.jar (~59 KB shaded bootstrap) AND the gradlew shell script.
# Extracting gradle-wrapper-*.jar from lib/plugins/ does NOT work: that file
# is the internal implementation JAR and is missing its own dependencies.
ENV GRADLE_VERSION=8.4
RUN wget -q https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip \
        -O /tmp/gradle.zip && \
    unzip -q /tmp/gradle.zip -d /opt && \
    rm /tmp/gradle.zip && \
    mkdir -p /tmp/wrappergen && \
    cd /tmp/wrappergen && \
    echo "rootProject.name = 'wrappergen'" > settings.gradle && \
    /opt/gradle-${GRADLE_VERSION}/bin/gradle wrapper \
        --gradle-version ${GRADLE_VERSION} \
        --no-daemon \
        -q && \
    mkdir -p /opt/gradle-wrapper && \
    cp gradle/wrapper/gradle-wrapper.jar /opt/gradle-wrapper/ && \
    cp gradlew /opt/gradle-wrapper/gradlew && \
    chmod +x /opt/gradle-wrapper/gradlew && \
    cd / && rm -rf /tmp/wrappergen

# ── Python dependencies ───────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── App source ────────────────────────────────────────────────────────────────
COPY . .

ENV PYTHONPATH=/app/src

CMD ["python", "src/pipeline.py"]
