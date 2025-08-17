package com.example.agent.repository;

import com.example.agent.model.ChatMessage;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {
    List<ChatMessage> findBySessionIdOrderByCreatedAtAsc(String sessionId);

    @Modifying
    @Query("delete from ChatMessage m where m.sessionId in :ids")
    int deleteBySessionIds(@Param("ids") List<String> ids);
}
