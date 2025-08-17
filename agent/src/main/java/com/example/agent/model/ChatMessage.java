package com.example.agent.model;

import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(
    name = "chat_messages",
    indexes = @Index(name = "idx_chat_messages_session", columnList = "sessionId, createdAt")
)
public class ChatMessage {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 255)
    private String sessionId;

    @Column(nullable = false, length = 32)
    private String role; // "user" | "assistant"

    @Column(columnDefinition = "text", nullable = false)
    private String content;

    @Column(nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    public Long getId() { return id; }
    public String getSessionId() { return sessionId; }
    public String getRole() { return role; }
    public String getContent() { return content; }
    public Instant getCreatedAt() { return createdAt; }

    public void setId(Long id) { this.id = id; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public void setRole(String role) { this.role = role; }
    public void setContent(String content) { this.content = content; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
