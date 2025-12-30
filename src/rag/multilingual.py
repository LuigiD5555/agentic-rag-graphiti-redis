"""Multilingual support for RAG system."""
from typing import Optional
from langdetect import detect, LangDetectException
from src.rag.audit import get_logger

log = get_logger(__name__)


class LanguageDetector:
    """Detects and manages language context for RAG queries."""

    # Language code mapping to full names
    LANGUAGE_NAMES = {
        'en': 'English',
        'es': 'Spanish',
        'zh-cn': 'Chinese (Simplified)',
        'zh-tw': 'Chinese (Traditional)',
        'ja': 'Japanese',
        'ko': 'Korean',
        'ru': 'Russian',
        'ar': 'Arabic',
        'fr': 'French',
        'de': 'German',
        'it': 'Italian',
        'pt': 'Portuguese',
        'hi': 'Hindi',
        'tr': 'Turkish',
        'vi': 'Vietnamese',
        'th': 'Thai',
    }

    # System prompts for different languages
    SYSTEM_PROMPTS = {
        'en': """You are a helpful assistant that answers questions based on the provided context.

Guidelines:
- Answer the question using ONLY the information from the provided context.
- If the context doesn't contain enough information to answer, say so clearly.
- Be concise but complete in your answers.
- Cite sources when relevant (mention document names/paths).
- If multiple sources provide conflicting information, acknowledge this.
""",
        'es': """You are a helpful assistant that answers questions based on the provided context.

Guidelines:
- Answer the question using ONLY the information from the provided context.
- If the context doesn't contain enough information to answer, say so clearly.
- Be concise but complete in your answers.
- Cite sources when relevant (mention document names/paths).
- If multiple sources provide conflicting information, acknowledge this.
""",
        'zh-cn': """你是一个有用的助手，根据提供的上下文回答问题。

指南：
- 仅使用提供的上下文中的信息回答问题。
- 如果上下文不包含足够的信息来回答，请明确说明。
- 答案要简洁但完整。
- 在相关时引用来源（提及文档名称/路径）。
- 如果多个来源提供相互矛盾的信息，请承认这一点。
""",
        'ja': """あなたは提供されたコンテキストに基づいて質問に答える役立つアシスタントです。

ガイドライン：
- 提供されたコンテキストの情報のみを使用して質問に答えてください。
- コンテキストに十分な情報が含まれていない場合は、明確に述べてください。
- 簡潔かつ完全な回答をしてください。
- 関連する場合はソースを引用してください（ドキュメント名/パスを記載）。
- 複数のソースが矛盾する情報を提供している場合は、それを認めてください。
""",
        'ko': """당신은 제공된 맥락을 기반으로 질문에 답하는 유용한 도우미입니다.

지침:
- 제공된 맥락의 정보만을 사용하여 질문에 답하십시오.
- 맥락에 답변하기에 충분한 정보가 없으면 명확하게 말하십시오.
- 간결하지만 완전한 답변을 제공하십시오.
- 관련이 있을 때 출처를 인용하십시오(문서 이름/경로 언급).
- 여러 출처가 상충되는 정보를 제공하는 경우 이를 인정하십시오.
""",
        'ru': """Вы полезный помощник, который отвечает на вопросы на основе предоставленного контекста.

Рекомендации:
- Отвечайте на вопрос, используя ТОЛЬКО информацию из предоставленного контекста.
- Если контекст не содержит достаточно информации для ответа, четко укажите это.
- Будьте кратки, но полны в своих ответах.
- Цитируйте источники, когда это уместно (упоминайте имена/пути документов).
- Если несколько источников предоставляют противоречивую информацию, признайте это.
""",
        'ar': """أنت مساعد مفيد يجيب على الأسئلة بناءً على السياق المقدم.

إرشادات:
- أجب على السؤال باستخدام المعلومات الواردة في السياق المقدم فقط.
- إذا كان السياق لا يحتوي على معلومات كافية للإجابة، فقل ذلك بوضوح.
- كن موجزًا ولكن كاملاً في إجاباتك.
- استشهد بالمصادر عند الاقتضاء (اذكر أسماء/مسارات المستندات).
- إذا قدمت مصادر متعددة معلومات متضاربة، فاعترف بذلك.
""",
        'fr': """Vous êtes un assistant utile qui répond aux questions en fonction du contexte fourni.

Directives :
- Répondez à la question en utilisant UNIQUEMENT les informations du contexte fourni.
- Si le contexte ne contient pas suffisamment d'informations pour répondre, dites-le clairement.
- Soyez concis mais complet dans vos réponses.
- Citez les sources le cas échéant (mentionnez les noms/chemins de documents).
- Si plusieurs sources fournissent des informations contradictoires, reconnaissez-le.
""",
        'de': """Sie sind ein hilfreicher Assistent, der Fragen basierend auf dem bereitgestellten Kontext beantwortet.

Richtlinien:
- Beantworten Sie die Frage NUR mit den Informationen aus dem bereitgestellten Kontext.
- Wenn der Kontext nicht genügend Informationen enthält, um zu antworten, sagen Sie dies klar.
- Seien Sie prägnant, aber vollständig in Ihren Antworten.
- Zitieren Sie Quellen, wenn relevant (erwähnen Sie Dokumentnamen/-pfade).
- Wenn mehrere Quellen widersprüchliche Informationen liefern, erkennen Sie dies an.
""",
        'pt': """Você é um assistente útil que responde perguntas com base no contexto fornecido.

Diretrizes:
- Responda à pergunta usando APENAS as informações do contexto fornecido.
- Se o contexto não contiver informações suficientes para responder, diga isso claramente.
- Seja conciso, mas completo em suas respostas.
- Cite as fontes quando relevante (mencione nomes/caminhos de documentos).
- Se várias fontes fornecerem informações conflitantes, reconheça isso.
""",
    }

    @staticmethod
    def detect_language(text: str) -> str:
        """Detect the language of the given text.

        Args:
            text: Input text to detect language for.

        Returns:
            ISO 639-1 language code (e.g., 'en', 'es', 'zh-cn', 'ja', 'ko', 'ru').
        """
        if not text or not text.strip():
            return 'en'  # Default to English

        try:
            lang_code = detect(text)
            log.debug("Detected language: %s for text: %s", lang_code, text[:50])
            return lang_code
        except LangDetectException as e:
            log.warning("Failed to detect language: %s. Defaulting to English.", e)
            return 'en'

    @classmethod
    def get_system_prompt(cls, language_code: str) -> str:
        """Get system prompt for the detected language.

        Args:
            language_code: ISO 639-1 language code.

        Returns:
            System prompt in the appropriate language.
        """
        # Try exact match first
        if language_code in cls.SYSTEM_PROMPTS:
            return cls.SYSTEM_PROMPTS[language_code]

        # Handle Chinese variants
        if language_code.startswith('zh'):
            return cls.SYSTEM_PROMPTS.get('zh-cn', cls.SYSTEM_PROMPTS['en'])

        # Default to English
        log.debug("No system prompt for language %s, using English", language_code)
        return cls.SYSTEM_PROMPTS['en']

    @classmethod
    def get_language_name(cls, language_code: str) -> str:
        """Get full language name from code.

        Args:
            language_code: ISO 639-1 language code.

        Returns:
            Full language name.
        """
        return cls.LANGUAGE_NAMES.get(language_code, f"Unknown ({language_code})")

    @classmethod
    def add_language_instruction(cls, system_prompt: str, language_code: str) -> str:
        """Add explicit instruction to respond in the detected language.

        Args:
            system_prompt: Base system prompt.
            language_code: Detected language code.

        Returns:
            Enhanced system prompt with language instruction.
        """
        if language_code == 'en':
            return system_prompt  # No need for explicit instruction in English

        language_name = cls.get_language_name(language_code)
        language_instructions = {
            'es': f"\n\nIMPORTANT: Always respond in Spanish.",
            'zh-cn': f"\n\n重要提示：始终用中文回答。",
            'ja': f"\n\n重要：常に日本語で回答してください。",
            'ko': f"\n\n중요: 항상 한국어로 답변하십시오.",
            'ru': f"\n\nВАЖНО: Всегда отвечайте на русском языке.",
            'ar': f"\n\nمهم: أجب دائمًا باللغة العربية.",
            'fr': f"\n\nIMPORTANT : Répondez TOUJOURS en français.",
            'de': f"\n\nWICHTIG: Antworten Sie IMMER auf Deutsch.",
            'pt': f"\n\nIMPORTANTE: Responda SEMPRE em português.",
        }

        instruction = language_instructions.get(
            language_code,
            f"\n\nIMPORTANT: Always respond in {language_name}."
        )

        return system_prompt + instruction


__all__ = ['LanguageDetector']
