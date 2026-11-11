# -*- coding: utf-8 -*-
"""Deterministic post-correction for common technical terms in ASR text."""
from __future__ import annotations

import re
import json
import os
from pathlib import Path


_TERMS = {
    "redis": "Redis",
    "mysql": "MySQL",
    "mysqld": "mysqld",
    "sql": "SQL",
    "jvm": "JVM",
    "jdk": "JDK",
    "jre": "JRE",
    "java": "Java",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "springcloud": "Spring Cloud",
    "spring cloud": "Spring Cloud",
    "mybatis": "MyBatis",
    "kafka": "Kafka",
    "rocketmq": "RocketMQ",
    "rabbitmq": "RabbitMQ",
    "elasticsearch": "Elasticsearch",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "nginx": "Nginx",
    "linux": "Linux",
    "netty": "Netty",
    "dubbo": "Dubbo",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "vue": "Vue",
    "react": "React",
    "webpack": "Webpack",
    "vite": "Vite",
    "html": "HTML",
    "css": "CSS",
    "qps": "QPS",
    "tps": "TPS",
    "api": "API",
    "http": "HTTP",
    "https": "HTTPS",
    "tcp": "TCP",
    "udp": "UDP",
    "mvcc": "MVCC",
    "cas": "CAS",
    "aqs": "AQS",
    "gc": "GC",
    "juc": "JUC",
    "threadpoolexecutor": "ThreadPoolExecutor",
    "thread pool executor": "ThreadPoolExecutor",
    "linkedblockingqueue": "LinkedBlockingQueue",
    "linked blocking queue": "LinkedBlockingQueue",
    "concurrenthashmap": "ConcurrentHashMap",
    "concurrent hashmap": "ConcurrentHashMap",
    "hashmap": "HashMap",
    "arraylist": "ArrayList",
    "linkedlist": "LinkedList",
    "countdownlatch": "CountDownLatch",
    "cyclicbarrier": "CyclicBarrier",
    "reentrantlock": "ReentrantLock",
    "volatile": "volatile",
    "synchronized": "synchronized",
    "bigdecimal": "BigDecimal",
    "prometheus": "Prometheus",
    "grafana": "Grafana",
    "jenkins": "Jenkins",
    "selenium": "Selenium",
    "jmeter": "JMeter",
    "appium": "Appium",
    "pytest": "pytest",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "flink": "Flink",
}

# Chinese ASR homophone patterns that are safe enough to correct in place.
_CN_ALIASES = {
    "瑞迪斯": "Redis",
    "卖sql": "MySQL",
    "麦sql": "MySQL",
    "斯普林布特": "Spring Boot",
    "斯普林克劳德": "Spring Cloud",
}

_GLOSSARY_CACHE: dict = {"path": "", "mtime": None, "terms": {}}


def _load_glossary() -> dict:
    from app import config
    path = str(getattr(config, "A11_ASR_TERM_GLOSSARY", "") or "")
    if not path or not os.path.isfile(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
        if (_GLOSSARY_CACHE["path"] == path
                and _GLOSSARY_CACHE["mtime"] == mtime):
            return dict(_GLOSSARY_CACHE["terms"])
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        raw = data.get("aliases") if isinstance(data, dict) else None
        terms = {
            str(alias).strip(): str(canonical).strip()
            for alias, canonical in (raw or {}).items()
            if str(alias).strip() and str(canonical).strip()
        }
        _GLOSSARY_CACHE["path"] = path
        _GLOSSARY_CACHE["mtime"] = mtime
        _GLOSSARY_CACHE["terms"] = terms
        return dict(terms)
    except Exception:
        return {}


def _replace_term(text: str, alias: str, canonical: str) -> tuple[str, int]:
    if re.search(r"[A-Za-z]", alias):
        pattern = (
            r"(?<![A-Za-z0-9_])"
            + re.escape(alias)
            + r"(?![A-Za-z0-9_])"
        )
        return re.subn(pattern, canonical, text, flags=re.IGNORECASE)
    return re.subn(re.escape(alias), canonical, text)


def correct_asr_terms(text: str) -> tuple[str, list[dict]]:
    """Return corrected text and an auditable list of replacements."""
    value = str(text or "")
    corrections: list[dict] = []
    for alias, canonical in sorted(
            {**_TERMS, **_CN_ALIASES, **_load_glossary()}.items(),
            key=lambda item: (-len(item[0]), item[0])):
        value, count = _replace_term(value, alias, canonical)
        if count:
            corrections.append({
                "from": alias,
                "to": canonical,
                "count": count,
            })
    return value, corrections
