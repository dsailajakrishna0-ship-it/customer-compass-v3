package com.customercompass.mcp;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * The Spring Boot MCP tool server: the same four tools as the FastMCP server (apps/api-py/app/mcp),
 * checked against the same contract (contracts/mcp-tools.json).
 */
@SpringBootApplication
public class McpJavaApplication {

    public static void main(String[] args) {
        SpringApplication.run(McpJavaApplication.class, args);
    }
}
