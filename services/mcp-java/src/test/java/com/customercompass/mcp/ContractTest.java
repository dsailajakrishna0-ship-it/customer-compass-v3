package com.customercompass.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.spec.McpSchema;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * The same check as contracts/check_server.py, run in-process: start the real server on a random port,
 * talk to it with a real MCP client over HTTP, and compare against contracts/mcp-tools.json. Only the
 * database and the Python API are replaced (by fakes seeded with the demo values the contract expects).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ContractTest {

    @TestConfiguration
    static class Fakes {
        @Bean
        @Primary
        FakeCrm fakeCrm() {
            return new FakeCrm();
        }

        @Bean
        @Primary
        RetrievalClient fakeRetrieval() {
            return (query, company) -> Map.of("status", "executed", "results", List.of());
        }
    }

    private static final JsonMapper JSON = JsonMapper.builder().build();

    @LocalServerPort
    int port;

    @Autowired
    FakeCrm crm;

    private JsonNode contract() throws Exception {
        return JSON.readTree(Files.readString(Path.of("../../contracts/mcp-tools.json")));
    }

    private McpSyncClient client() {
        var transport = HttpClientStreamableHttpTransport.builder("http://localhost:" + port)
                .endpoint("/mcp")
                .build();
        McpSyncClient client = McpClient.sync(transport).build();
        client.initialize();
        return client;
    }

    @Test
    @SuppressWarnings("unchecked")
    void theOfferedToolsMatchTheContract() throws Exception {
        JsonNode want = contract().get("tools");
        List<String> problems = new ArrayList<>();
        try (McpSyncClient client = client()) {
            Map<String, McpSchema.Tool> offered = new TreeMap<>();
            client.listTools().tools().forEach(t -> offered.put(t.name(), t));
            want.propertyNames().forEach(name -> {
                if (!offered.containsKey(name)) {
                    problems.add("does not offer " + name);
                    return;
                }
                Map<String, Object> schema = offered.get(name).inputSchema();
                Map<String, Object> props = (Map<String, Object>) schema.getOrDefault("properties", Map.of());
                List<String> required = (List<String>) schema.getOrDefault("required", List.of());
                JsonNode wantTool = want.get(name);
                List<String> wantRequired = new ArrayList<>();
                wantTool.get("required").forEach(n -> wantRequired.add(n.asString()));
                if (!new TreeMap<>(Map.of("r", required.stream().sorted().toList()))
                        .equals(new TreeMap<>(Map.of("r", wantRequired.stream().sorted().toList())))) {
                    problems.add(name + ": required is " + required + ", contract says " + wantRequired);
                }
                Map<String, String> gotProps = new TreeMap<>();
                props.forEach((k, v) -> gotProps.put(k, String.valueOf(((Map<String, Object>) v).get("type"))));
                Map<String, String> wantProps = new TreeMap<>();
                wantTool.get("properties").propertyNames().forEach(k ->
                        wantProps.put(k, wantTool.get("properties").get(k).asString().replace("?", "")));
                if (!gotProps.equals(wantProps)) {
                    problems.add(name + ": arguments are " + gotProps + ", contract says " + wantProps);
                }
            });
            offered.keySet().stream()
                    .filter(n -> want.get(n) == null)
                    .forEach(n -> problems.add("offers " + n + ", which the contract does not list"));
        }
        assertThat(problems).isEmpty();
    }

    @Test
    void everyContractCaseGetsTheExpectedAnswer() throws Exception {
        List<String> problems = new ArrayList<>();
        try (McpSyncClient client = client()) {
            for (JsonNode c : contract().get("cases")) {
                Map<String, Object> args = JSON.convertValue(c.get("arguments"), Map.class);
                McpSchema.CallToolResult result = client.callTool(new McpSchema.CallToolRequest(c.get("tool").asString(), args));
                String text = ((McpSchema.TextContent) result.content().get(0)).text();
                JsonNode answer = JSON.readTree(text);
                c.get("expect").propertyNames().forEach(path -> {
                    JsonNode got = answer;
                    for (String part : path.split("\\.")) {
                        got = got == null ? null : (got.isArray() ? got.get(Integer.parseInt(part)) : got.get(part));
                    }
                    JsonNode want = c.get("expect").get(path);
                    boolean same = got != null && (want.isNumber() ? got.isNumber() && got.decimalValue().compareTo(want.decimalValue()) == 0 : got.equals(want));
                    if (!same) {
                        problems.add(c.get("id").asString() + ": " + path + " is " + got + ", wanted " + want);
                    }
                });
            }
        }
        assertThat(problems).isEmpty();
        assertThat(crm.createdTasks).as("contract cases never write").isEmpty();
    }
}
