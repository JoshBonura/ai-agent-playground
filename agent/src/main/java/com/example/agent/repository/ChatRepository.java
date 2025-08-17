package com.example.agent.repository;

import com.example.agent.model.Chat;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Query;

import java.util.List;
import java.util.Optional;

public interface ChatRepository extends JpaRepository<Chat, Long> {
    Optional<Chat> findBySessionId(String sessionId);

    @Modifying
    @Query("delete from Chat c where c.sessionId in :ids")
    int deleteBySessionIds(@Param("ids") List<String> ids);

    @Query("""
       select c from Chat c
       where c.updatedAt <= :ceiling
       """)
Page<Chat> findAllBefore(Instant ceiling, Pageable pageable);
}
