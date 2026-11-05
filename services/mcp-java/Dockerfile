# Image: builds the Spring Boot MCP server with Maven, runs it on a slim Java 21 runtime on port 8003
FROM maven:3.9.11-eclipse-temurin-21 AS build
WORKDIR /build

# Dependencies first (cached layer, unchanged unless pom.xml changes)
COPY pom.xml ./
RUN mvn -q -B dependency:go-offline

# Then the code; tests run in CI (and with `just java-test`), not in the image build
COPY src ./src
RUN mvn -q -B -DskipTests package

FROM eclipse-temurin:21-jre
WORKDIR /app
# Pull the patched apt now: the base image lags behind Ubuntu security fixes (Trivy: CVE-2026-109518).
# Remove this line once a rebuilt eclipse-temurin image carries apt 3.2.1ubuntu0.1 or newer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade apt libapt-pkg7.0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /build/target/mcp-java-0.1.0.jar ./app.jar

# Run as an unprivileged user (Trivy DS-0002)
RUN useradd --system --no-create-home --uid 10001 appuser
USER appuser

EXPOSE 8003
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
