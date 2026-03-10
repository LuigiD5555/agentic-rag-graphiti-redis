"""Sanitizer for query and context text with privacy controls.

This module provides:
- Secrets stripping (always enabled, non-negotiable)
- PII masking (controlled by LLM_PII_ALLOWED switch)
- Placeholder replacement with structure preservation
- Audit logging for privacy events
"""

import re
import time
from typing import Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class PIICategory(Enum):
    """Categories of Personally Identifiable Information."""
    PERSON = "PERSON"
    RFC = "RFC"  # Mexican tax ID
    NSS = "NSS"  # Mexican social security number
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"
    PATH = "PATH"  # File paths that may reveal user information
    CREDIT_CARD = "CREDIT_CARD"
    IP_ADDRESS = "IP_ADDRESS"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"


@dataclass
class RedactionReport:
    """Report of redactions performed."""
    total_redactions: int = 0
    by_category: Dict[PIICategory, int] = None
    secrets_stripped: int = 0
    pii_masked: int = 0
    
    def __post_init__(self):
        if self.by_category is None:
            self.by_category = {category: 0 for category in PIICategory}
    
    def increment_category(self, category: PIICategory, count: int = 1):
        """Increment count for a PII category."""
        self.by_category[category] = self.by_category.get(category, 0) + count
        self.total_redactions += count
        self.pii_masked += count
    
    def increment_secrets(self, count: int = 1):
        """Increment secrets count."""
        self.secrets_stripped += count
        self.total_redactions += count
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "total_redactions": self.total_redactions,
            "by_category": {
                category.value: count
                for category, count in self.by_category.items()
            },
            "secrets_stripped": self.secrets_stripped,
            "pii_masked": self.pii_masked,
        }


class Sanitizer:
    """Sanitizer for text with privacy controls."""
    
    # Secrets patterns (always stripped, non-negotiable)
    SECRET_PATTERNS = {
        "API_KEY": r'(?i)(api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*[\'"][a-zA-Z0-9_\-]{20,}[\'"]',
        "BEARER_TOKEN": r'(?i)bearer\s+[a-zA-Z0-9_\-]{20,}',
        "BASIC_AUTH": r'(?i)basic\s+[a-zA-Z0-9+/=]{20,}',
        "PRIVATE_KEY": r'-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----',
        "PASSWORD": r'(?i)(password|passwd|pwd)\s*[:=]\s*[\'"][^\'"]{6,}[\'"]',
        "AWS_KEY": r'(?i)AKIA[0-9A-Z]{16}',
        "GITHUB_TOKEN": r'(?i)gh[pousr]_[a-zA-Z0-9_]{36}',
        "SLACK_TOKEN": r'(?i)xox[baprs]-[0-9a-zA-Z-]{10,48}',
    }
    
    # PII patterns (masked when LLM_PII_ALLOWED=false)
    PII_PATTERNS = {
        PIICategory.EMAIL: r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b',
        PIICategory.PHONE: r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        PIICategory.RFC: r'\b[A-Z&Ñ]{3,4}[0-9]{6}[A-Z0-9]{3}\b',
        PIICategory.NSS: r'\b\d{2}-\d{2}-\d{4}-\d{1}\b',
        PIICategory.CREDIT_CARD: r'\b(?:\d[ -]*?){13,16}\b',
        PIICategory.IP_ADDRESS: r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        PIICategory.DATE_OF_BIRTH: r'\b(?:0[1-9]|[12][0-9]|3[01])[-/.](?:0[1-9]|1[0-2])[-/.](?:19|20)\d{2}\b',
    }
    
    # Placeholder mapping
    PLACEHOLDERS = {
        PIICategory.PERSON: "PERSON_{n}",
        PIICategory.RFC: "RFC_{n}",
        PIICategory.NSS: "NSS_{n}",
        PIICategory.EMAIL: "EMAIL_{n}",
        PIICategory.PHONE: "PHONE_{n}",
        PIICategory.ADDRESS: "ADDRESS_{n}",
        PIICategory.PATH: "PATH_{n}",
        PIICategory.CREDIT_CARD: "CREDIT_CARD_{n}",
        PIICategory.IP_ADDRESS: "IP_ADDRESS_{n}",
        PIICategory.DATE_OF_BIRTH: "DATE_OF_BIRTH_{n}",
    }
    
    def __init__(self, session_id: str):
        """Initialize sanitizer for a session.
        
        Args:
            session_id: User session identifier
        """
        self.session_id = session_id
        self.sqlite_manager = get_sqlite_manager()
        self.session_repo = self.sqlite_manager.get_session_repository()
        self.audit_repo = self.sqlite_manager.get_audit_repository()
        
        # Load session preferences
        self.session = self.session_repo.get_or_create_session(session_id, int(time.time()))
        self.llm_pii_allowed = self.session.llm_pii_allowed
        
        log.info("Sanitizer initialized for session %s (LLM_PII_ALLOWED=%s)", 
                 session_id, self.llm_pii_allowed)
    
    def sanitize_query(self, query_text: str) -> Tuple[str, RedactionReport, Dict[str, str]]:
        """Sanitize query text based on privacy settings.
        
        Args:
            query_text: Original query text
            
        Returns:
            Tuple of (sanitized_text, redaction_report, privacy_map)
        """
        import time
        
        redaction_report = RedactionReport()
        privacy_map = {}  # Maps placeholders to original values (internal only)
        
        # Step 1: Always strip secrets (non-negotiable)
        sanitized_text = self._strip_secrets(query_text, redaction_report)
        
        # Step 2: Mask PII if LLM_PII_ALLOWED=false
        if not self.llm_pii_allowed:
            sanitized_text = self._mask_pii(sanitized_text, redaction_report, privacy_map)
        
        # Log audit event if redactions occurred
        if redaction_report.total_redactions > 0:
            self.audit_repo.log_event(
                session_id=self.session_id,
                event_type="QUERY_SANITIZED",
                metadata={
                    "original_length": len(query_text),
                    "sanitized_length": len(sanitized_text),
                    "redaction_report": redaction_report.to_dict(),
                    "llm_pii_allowed": self.llm_pii_allowed,
                },
                event_at=int(time.time())
            )
        
        return sanitized_text, redaction_report, privacy_map
    
    def sanitize_context(self, context_text: str) -> Tuple[str, RedactionReport]:
        """Sanitize context text (retrieved documents) based on privacy settings.
        
        Args:
            context_text: Original context text
            
        Returns:
            Tuple of (sanitized_text, redaction_report)
        """
        import time
        
        redaction_report = RedactionReport()
        
        # Step 1: Always strip secrets (non-negotiable)
        sanitized_text = self._strip_secrets(context_text, redaction_report)
        
        # Step 2: Mask PII if LLM_PII_ALLOWED=false
        if not self.llm_pii_allowed:
            # For context, we don't need privacy map (not used for reconstruction)
            sanitized_text = self._mask_pii(sanitized_text, redaction_report, {})
        
        # Log audit event if redactions occurred
        if redaction_report.total_redactions > 0:
            self.audit_repo.log_event(
                session_id=self.session_id,
                event_type="CONTEXT_SANITIZED",
                metadata={
                    "original_length": len(context_text),
                    "sanitized_length": len(sanitized_text),
                    "redaction_report": redaction_report.to_dict(),
                    "llm_pii_allowed": self.llm_pii_allowed,
                },
                event_at=int(time.time())
            )
        
        return sanitized_text, redaction_report
    
    def update_privacy_setting(self, llm_pii_allowed: bool) -> None:
        """Update privacy setting for the session.
        
        Args:
            llm_pii_allowed: New privacy setting
        """
        import time
        
        old_setting = self.llm_pii_allowed
        self.llm_pii_allowed = llm_pii_allowed
        
        # Update session in database
        self.session_repo.update_session(
            session_id=self.session_id,
            llm_pii_allowed=llm_pii_allowed,
            now_ts=int(time.time())
        )
        
        # Log audit event
        self.audit_repo.log_event(
            session_id=self.session_id,
            event_type="PII_MODE_CHANGED",
            metadata={
                "old_setting": old_setting,
                "new_setting": llm_pii_allowed,
                "timestamp": int(time.time()),
            },
            event_at=int(time.time())
        )
        
        log.info("Privacy setting updated for session %s: LLM_PII_ALLOWED=%s", 
                 self.session_id, llm_pii_allowed)
    
    def _strip_secrets(self, text: str, report: RedactionReport) -> str:
        """Strip secrets from text (always enabled).
        
        Args:
            text: Input text
            report: Redaction report to update
            
        Returns:
            Text with secrets replaced with [REDACTED]
        """
        sanitized_text = text
        
        for secret_name, pattern in self.SECRET_PATTERNS.items():
            def replace_secret(match):
                report.increment_secrets()
                return f"[REDACTED_{secret_name}]"
            
            sanitized_text = re.sub(pattern, replace_secret, sanitized_text)
        
        return sanitized_text
    
    def _mask_pii(self, text: str, report: RedactionReport, privacy_map: Dict[str, str]) -> str:
        """Mask PII in text with placeholders.
        
        Args:
            text: Input text
            report: Redaction report to update
            privacy_map: Dictionary to store mapping from placeholders to original values
            
        Returns:
            Text with PII replaced with placeholders
        """
        sanitized_text = text
        counters = {category: 1 for category in PIICategory}
        
        for category, pattern in self.PII_PATTERNS.items():
            def replace_pii(match, cat=category):
                original = match.group(0)
                placeholder = self.PLACEHOLDERS[cat].format(n=counters[cat])
                counters[cat] += 1
                
                # Store mapping (internal only, never sent to LLM)
                privacy_map[placeholder] = original
                
                # Update report
                report.increment_category(cat)
                
                return placeholder
            
            sanitized_text = re.sub(pattern, replace_pii, sanitized_text)
        
        # Additional heuristic for person names (context-dependent)
        sanitized_text = self._mask_person_names(sanitized_text, report, privacy_map, counters)
        
        # Mask file paths that may reveal user information
        sanitized_text = self._mask_file_paths(sanitized_text, report, privacy_map, counters)
        
        # Mask addresses (heuristic)
        sanitized_text = self._mask_addresses(sanitized_text, report, privacy_map, counters)
        
        return sanitized_text
    
    def _mask_person_names(self, text: str, report: RedactionReport, 
                          privacy_map: Dict[str, str], counters: Dict[PIICategory, int]) -> str:
        """Mask person names using heuristic rules.
        
        This is a simplified implementation. In production, you might want to use
        a proper NER (Named Entity Recognition) model.
        
        Args:
            text: Input text
            report: Redaction report
            privacy_map: Privacy mapping dictionary
            counters: Category counters
            
        Returns:
            Text with person names masked
        """
        # Simple heuristic: capitalized words that appear in certain contexts
        # This is a basic implementation - consider using spaCy or similar for production
        
        # Look for patterns like "Mr. Smith", "Dr. Johnson", "Maria Garcia", etc.
        name_pattern = r'\b(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)\s+[A-Z][a-z]+\b'
        
        def replace_name(match):
            original = match.group(0)
            placeholder = self.PLACEHOLDERS[PIICategory.PERSON].format(
                n=counters[PIICategory.PERSON]
            )
            counters[PIICategory.PERSON] += 1
            
            privacy_map[placeholder] = original
            report.increment_category(PIICategory.PERSON)
            
            return placeholder
        
        return re.sub(name_pattern, replace_name, text)
    
    def _mask_file_paths(self, text: str, report: RedactionReport,
                        privacy_map: Dict[str, str], counters: Dict[PIICategory, int]) -> str:
        """Mask file paths that may reveal user information.
        
        Args:
            text: Input text
            report: Redaction report
            privacy_map: Privacy mapping dictionary
            counters: Category counters
            
        Returns:
            Text with file paths masked
        """
        # Pattern for common file paths
        path_pattern = r'\b(?:/home/|/Users/|C:\\Users\\|~/)[^\s<>:"|?*]+\b'
        
        def replace_path(match):
            original = match.group(0)
            placeholder = self.PLACEHOLDERS[PIICategory.PATH].format(
                n=counters[PIICategory.PATH]
            )
            counters[PIICategory.PATH] += 1
            
            privacy_map[placeholder] = original
            report.increment_category(PIICategory.PATH)
            
            return placeholder
        
        return re.sub(path_pattern, replace_path, text)
    
    def _mask_addresses(self, text: str, report: RedactionReport,
                       privacy_map: Dict[str, str], counters: Dict[PIICategory, int]) -> str:
        """Mask addresses using heuristic patterns.
        
        Args:
            text: Input text
            report: Redaction report
            privacy_map: Privacy mapping dictionary
            counters: Category counters
            
        Returns:
            Text with addresses masked
        """
        # Simple address pattern (street numbers, common street terms)
        address_pattern = r'\b\d+\s+(?:Ave|Avenue|St|Street|Rd|Road|Blvd|Boulevard|Ln|Lane)\b'
        
        def replace_address(match):
            original = match.group(0)
            placeholder = self.PLACEHOLDERS[PIICategory.ADDRESS].format(
                n=counters[PIICategory.ADDRESS]
            )
            counters[PIICategory.ADDRESS] += 1
            
            privacy_map[placeholder] = original
            report.increment_category(PIICategory.ADDRESS)
            
            return placeholder
        
        return re.sub(address_pattern, replace_address, text)


# Global sanitizer factory
_sanitizer_cache = {}


def get_sanitizer(session_id: str) -> Sanitizer:
    """Get or create sanitizer for a session.
    
    Args:
        session_id: User session identifier
        
    Returns:
        Sanitizer instance
    """
    if session_id not in _sanitizer_cache:
        _sanitizer_cache[session_id] = Sanitizer(session_id)
    
    return _sanitizer_cache[session_id]


def clear_sanitizer_cache():
    """Clear sanitizer cache (useful for testing)."""
    _sanitizer_cache.clear()


__all__ = ["Sanitizer", "get_sanitizer", "clear_sanitizer_cache", "RedactionReport", "PIICategory"]
