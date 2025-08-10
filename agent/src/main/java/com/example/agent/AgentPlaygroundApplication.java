package com.example.agent;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class AgentPlaygroundApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentPlaygroundApplication.class, args);
        System.out.println("🚀 Agent Playground started without Elasticsearch!");
    }
}
