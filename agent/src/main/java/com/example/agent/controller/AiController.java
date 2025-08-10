package com.example.agent.controller;

import org.springframework.web.bind.annotation.*;

import com.example.agent.service.AiService;

import java.util.Map;

@RestController
@RequestMapping("/api/ai")
public class AiController {

    private final AiService aiService;

    public AiController(AiService aiService) {
        this.aiService = aiService;
    }

    @PostMapping("/generate")
    public String generate(@RequestBody Map<String, String> body) throws Exception {
        String prompt = body.get("prompt");
        return aiService.generateResponse(prompt);
    }
}
