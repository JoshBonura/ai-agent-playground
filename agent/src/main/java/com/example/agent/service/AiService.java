package com.example.agent.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Map;

@Service
public class AiService {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final HttpClient CLIENT = HttpClient.newHttpClient();
    private static final URI MODEL_URI = URI.create("http://127.0.0.1:8000/generate");

    public String generateResponse(String prompt) throws Exception {
        // ✅ Let Jackson escape newlines/quotes automatically
        String body = MAPPER.writeValueAsString(Map.of("prompt", prompt));

        HttpRequest request = HttpRequest.newBuilder()
                .uri(MODEL_URI)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();

        HttpResponse<String> response = CLIENT.send(request, HttpResponse.BodyHandlers.ofString());

        if (response.statusCode() != 200) {
            throw new RuntimeException(
                    "AI request failed: " + response.statusCode() + " — " + response.body()
            );
        }

        Map<String, Object> jsonMap = MAPPER.readValue(
                response.body(),
                new TypeReference<Map<String, Object>>() {}
        );

        return String.valueOf(jsonMap.getOrDefault("response", "No response"));
    }
}
