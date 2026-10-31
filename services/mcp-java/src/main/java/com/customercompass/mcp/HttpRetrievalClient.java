package com.customercompass.mcp;

import java.net.http.HttpClient;
import java.util.HashMap;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/** Calls POST /api/v1/documents/search on the Python API (which also writes the audit row for this tool). */
@Component
public class HttpRetrievalClient implements RetrievalClient {

    private final RestClient http;

    public HttpRetrievalClient(@Value("${compass.api-url}") String apiUrl) {
        // HTTP/1.1 only: by default the JDK client first offers an upgrade to HTTP/2, and uvicorn (the Python
        // API's server) then loses the request body of a POST (the API answered 422 "body: Field required").
        HttpClient jdk = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
        this.http = RestClient.builder()
                .baseUrl(apiUrl)
                .requestFactory(new JdkClientHttpRequestFactory(jdk))
                .build();
    }

    @Override
    public Map<String, Object> search(String query, String companyName) {
        Map<String, Object> body = new HashMap<>();
        body.put("query", query);
        if (companyName != null) {
            body.put("companyName", companyName);
        }
        try {
            return http.post()
                    .uri("/api/v1/documents/search")
                    .body(body)
                    .retrieve()
                    .body(new ParameterizedTypeReference<Map<String, Object>>() {});
        } catch (RuntimeException error) {
            throw new IllegalStateException("Document search failed: the Python API did not answer (" + error.getMessage() + ")", error);
        }
    }
}
