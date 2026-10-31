package com.customercompass.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

/** The call to the Python API, against a tiny local HTTP server (no real API needed). */
class HttpRetrievalClientTest {

    private HttpServer server;
    private final AtomicReference<String> upgradeHeader = new AtomicReference<>("none");

    @AfterEach
    void stop() {
        if (server != null) {
            server.stop(0);
        }
    }

    private String start(int status, String body, AtomicReference<String> seenBody, AtomicReference<String> seenPath)
            throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            upgradeHeader.set(String.valueOf(exchange.getRequestHeaders().getFirst("Upgrade")));
            seenPath.set(exchange.getRequestMethod() + " " + exchange.getRequestURI().getPath());
            seenBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] out = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, out.length);
            exchange.getResponseBody().write(out);
            exchange.close();
        });
        server.start();
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @Test
    void sendsTheQueryAndCompanyAndReturnsTheApisAnswerUnchanged() throws IOException {
        var body = new AtomicReference<String>();
        var path = new AtomicReference<String>();
        String url = start(200, "{\"status\":\"executed\",\"results\":[{\"title\":\"Onboarding email\"}]}", body, path);

        Map<String, Object> result = new HttpRetrievalClient(url).search("pricing", "Acme");

        assertThat(path.get()).isEqualTo("POST /api/v1/documents/search");
        assertThat(body.get()).contains("\"query\":\"pricing\"").contains("\"companyName\":\"Acme\"");
        assertThat(result).containsEntry("status", "executed");
    }

    @Test
    void neverAsksForAnHttp2UpgradeBecauseUvicornLosesThePostBodyThen() throws IOException {
        String url = start(200, "{\"status\":\"executed\",\"results\":[]}", new AtomicReference<>(), new AtomicReference<>());
        new HttpRetrievalClient(url).search("pricing", null);
        assertThat(upgradeHeader.get()).isEqualTo("null");
    }

    @Test
    void leavesTheCompanyOutWhenThereIsNone() throws IOException {
        var body = new AtomicReference<String>();
        String url = start(200, "{\"status\":\"executed\",\"results\":[]}", body, new AtomicReference<>());
        new HttpRetrievalClient(url).search("pricing", null);
        assertThat(body.get()).doesNotContain("companyName");
    }

    @Test
    void anApiErrorBecomesAClearToolError() throws IOException {
        String url = start(500, "{\"error\":\"boom\"}", new AtomicReference<>(), new AtomicReference<>());
        assertThatThrownBy(() -> new HttpRetrievalClient(url).search("pricing", null))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("Document search failed");
    }
}
