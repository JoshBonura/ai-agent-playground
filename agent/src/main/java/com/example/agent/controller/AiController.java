// agent/src/main/java/com/example/agent/controller/AiController.java
package com.example.agent.controller;

import com.example.agent.service.AiService;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;

@RestController
@RequestMapping("/api/ai")
public class AiController {

    private final AiService aiService;

    public AiController(AiService aiService) {
        this.aiService = aiService;
    }

    @PostMapping(value = "/generate/stream", produces = MediaType.TEXT_PLAIN_VALUE)
    public ResponseEntity<ResponseBodyEmitter> streamGenerate(@RequestBody JsonNode body) {
        ResponseBodyEmitter emitter = new ResponseBodyEmitter(0L); // no server timeout
        aiService.streamResponse(body, emitter);

        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.CACHE_CONTROL, "no-cache");
        headers.set("X-Accel-Buffering", "no");
        headers.set(HttpHeaders.CONNECTION, "keep-alive");
        headers.set(HttpHeaders.TRANSFER_ENCODING, "chunked");
        return ResponseEntity.ok().headers(headers).body(emitter);
    }

    @PostMapping("/cancel/{sessionId}")
    public ResponseEntity<Void> cancel(@PathVariable String sessionId) {
        aiService.cancelSession(sessionId);
        return ResponseEntity.ok().build();
    }

    @GetMapping("/debug/ping")
    public String ping() {
        System.out.println("[agent] /api/ai/debug/ping hit");
        return "pong";
    }

    // Optional: quick streaming echo to verify chunking from Spring to client
    @GetMapping(value = "/debug/echo", produces = MediaType.TEXT_PLAIN_VALUE)
    public ResponseEntity<ResponseBodyEmitter> echo() {
        ResponseBodyEmitter emitter = new ResponseBodyEmitter(0L);
        new Thread(() -> {
            try {
                emitter.send("A", MediaType.TEXT_PLAIN);
                Thread.sleep(200);
                emitter.send("B", MediaType.TEXT_PLAIN);
                Thread.sleep(200);
                emitter.send("C", MediaType.TEXT_PLAIN);
                emitter.complete();
            } catch (Exception e) {
                try { emitter.completeWithError(e); } catch (Exception ignore) {}
            }
        }).start();

        HttpHeaders h = new HttpHeaders();
        h.set(HttpHeaders.CACHE_CONTROL, "no-cache");
        h.set("X-Accel-Buffering", "no");
        h.set(HttpHeaders.CONNECTION, "keep-alive");
        return ResponseEntity.ok().headers(h).body(emitter);
    }
}
