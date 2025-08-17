// agent/src/main/java/com/example/agent/service/AiService.java
package com.example.agent.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.InputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

@Service
public class AiService {

    // Pull from Spring config. In application.properties you already have:
    // ai.service.url=${AI_SERVICE_URL:http://127.0.0.1:8001}
    @Value("${ai.service.url}")
    private String modelBase;

    // Force HTTP/1.1; keeps things predictable with uvicorn/h11
    private final HttpClient client = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    private final ObjectMapper mapper = new ObjectMapper();

    public void streamResponse(JsonNode body, ResponseBodyEmitter emitter) {
        try {
            // Serialize the exact body Spring received
            String reqJson = mapper.writeValueAsString(body);

            System.out.println("[agent] modelBase=" + modelBase + " bytes=" + reqJson.getBytes(StandardCharsets.UTF_8).length);

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(modelBase + "/generate/stream"))
                    .timeout(Duration.ofSeconds(30)) // connect + headers
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/plain")
                    .POST(HttpRequest.BodyPublishers.ofString(reqJson, StandardCharsets.UTF_8)) // sets Content-Length
                    .build();

            client.sendAsync(request, HttpResponse.BodyHandlers.ofInputStream())
                  .thenAccept(resp -> {
                      if (resp.statusCode() / 100 != 2) {
                          // Read error body so you see FastAPI's validation details
                          String errText = "(no body)";
                          try (InputStream es = resp.body()) {
                              errText = new String(es.readAllBytes(), StandardCharsets.UTF_8);
                          } catch (Exception ignore) {}
                          try {
                              String forwardedPretty = mapper.writerWithDefaultPrettyPrinter().writeValueAsString(body);
                              emitter.send(("[agent] upstream status: " + resp.statusCode() + "\n"
                                           + "[agent] upstream error body: " + errText + "\n"
                                           + "[agent] forwarded JSON:\n" + forwardedPretty + "\n"),
                                           MediaType.TEXT_PLAIN);
                              emitter.complete();
                          } catch (Exception e) {
                              try { emitter.completeWithError(e); } catch (Throwable t) {}
                          }
                          return;
                      }

                      try (var is = resp.body();
                           var reader = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8), 8192)) {
                          char[] buf = new char[8192];
                          int n;
                          while ((n = reader.read(buf)) != -1) {
                              emitter.send(new String(buf, 0, n), MediaType.TEXT_PLAIN);
                          }
                          emitter.complete();
                      } catch (Exception e) {
                          String name = e.getClass().getName();
                          // Normal when client clicks "Stop"
                          if (name.contains("ClientAbort") || name.contains("BrokenPipe")) {
                              try { emitter.complete(); } catch (Throwable ignored) {}
                          } else {
                              try { emitter.completeWithError(e); } catch (Throwable ignored) {}
                          }
                      }
                  })
                  .exceptionally(ex -> { try { emitter.completeWithError(ex); } catch (Throwable ignored) {} return null; });

        } catch (Exception e) {
            try { emitter.completeWithError(e); } catch (Throwable ignored) {}
        }
    }

    // Best-effort server-side cancel (called by your Stop button)
    public void cancelSession(String sessionId) {
        try {
            String encoded = URLEncoder.encode(sessionId, StandardCharsets.UTF_8);
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(modelBase + "/cancel/" + encoded))
                    .timeout(Duration.ofSeconds(5))
                    .POST(HttpRequest.BodyPublishers.noBody())
                    .build();
            client.sendAsync(req, HttpResponse.BodyHandlers.discarding());
        } catch (Exception ignore) {}
    }
}
