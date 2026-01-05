"""Intent classifier for RAG routing decisions."""
from typing import Literal
from src.rag.intent.language_detector import SimpleLanguageDetector
from src.rag.audit import get_logger

log = get_logger(__name__)

IntentType = Literal["SMALL_TALK", "PERSONAL_CHAT", "CONTROL", "GENERAL_KNOWLEDGE", "PERSONAL_KB"]


class IntentClassifier:
    """Classify user query intent for RAG routing.

    Intent categories (based on dialogue acts):
    - SMALL_TALK: Greetings, thanks, confirmations (no RAG needed)
    - PERSONAL_CHAT: Personal questions about the bot (no RAG needed)
    - CONTROL: Format/style commands like "resume", "translate" (no RAG needed initially)
    - GENERAL_KNOWLEDGE: Informational queries (LLM-only by default)
    - PERSONAL_KB: Queries referencing user's documents (requires RAG)
    """

    # Multi-language patterns for SMALL_TALK
    GREETINGS = {
        'es': ['hola', 'buenas', 'buenos días', 'buenas tardes', 'buenas noches', 'hey', 'qué tal'],
        'en': ['hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening'],
        'fr': ['salut', 'bonjour', 'bonsoir'],
        'de': ['hallo', 'guten tag', 'guten morgen', 'guten abend'],
        'ja': ['こんにちは', 'おはよう', 'こんばんは'],
        'ko': ['안녕하세요', '안녕'],
        'ru': ['привет', 'здравствуйте', 'добрый день'],
        'zh': ['你好', '您好', '早上好'],
    }

    THANKS = {
        'es': ['gracias', 'muchas gracias', 'te agradezco'],
        'en': ['thanks', 'thank you', 'thx', 'appreciate'],
        'fr': ['merci', 'merci beaucoup'],
        'de': ['danke', 'vielen dank'],
        'ja': ['ありがとう', 'ありがとうございます'],
        'ko': ['감사합니다', '고맙습니다'],
        'ru': ['спасибо', 'благодарю'],
        'zh': ['谢谢', '谢了'],
    }

    GOODBYES = {
        'es': ['adiós', 'hasta luego', 'nos vemos', 'chao', 'bye'],
        'en': ['bye', 'goodbye', 'see you', 'later'],
        'fr': ['au revoir', 'salut', 'à bientôt'],
        'de': ['tschüss', 'auf wiedersehen'],
        'ja': ['さようなら', 'バイバイ', 'じゃあね'],
        'ko': ['안녕', '잘 가', '다음에 봐'],
        'ru': ['пока', 'до свидания'],
        'zh': ['再见', '拜拜'],
    }

    AFFIRMATIONS = {
        'es': ['ok', 'vale', 'sí', 'si', 'claro', 'entendido', 'perfecto', 'ajá'],
        'en': ['ok', 'okay', 'yes', 'yep', 'yeah', 'got it', 'sure', 'fine'],
        'fr': ['ok', 'd\'accord', 'oui', 'bien'],
        'de': ['ok', 'ja', 'gut', 'klar'],
        'ja': ['はい', 'OK', 'わかりました', 'そうです'],
        'ko': ['네', '예', '알겠습니다', 'OK'],
        'ru': ['да', 'хорошо', 'понятно', 'ОК'],
        'zh': ['是', '好', '行', 'OK', '明白'],
    }

    NEGATIONS = {
        'es': ['no', 'nop', 'nope', 'para nada'],
        'en': ['no', 'nope', 'nah', 'not really'],
        'fr': ['non', 'pas du tout'],
        'de': ['nein', 'nicht'],
        'ja': ['いいえ', 'ちがう', '違います'],
        'ko': ['아니요', '아니', '아니에요'],
        'ru': ['нет', 'не'],
        'zh': ['不', '不是', '没有'],
    }

    # Multi-language patterns for PERSONAL_CHAT (anthropomorphism)
    BOT_NAME_PATTERNS = {
        'es': ['tu nombre', 'cómo te llamas', 'quién eres', 'eres humano', 'eres real'],
        'en': ['your name', 'what\'s your name', 'who are you', 'are you human', 'are you real'],
        'fr': ['ton nom', 'comment tu t\'appelles', 'qui es-tu'],
        'de': ['dein name', 'wie heißt du', 'wer bist du'],
        'ja': ['あなたの名前', '名前は', '誰ですか'],
        'ko': ['너 이름', '이름 뭐야', '누구야'],
        'ru': ['твоё имя', 'как тебя зовут', 'кто ты'],
        'zh': ['你叫什么', '你的名字', '你是谁'],
    }

    BOT_FEELINGS_PATTERNS = {
        'es': ['cómo te sientes', 'tienes sentimientos', 'te gusta', 'estás bien', 'qué opinas'],
        'en': ['how do you feel', 'do you have feelings', 'do you like', 'are you ok', 'what do you think'],
        'fr': ['comment tu te sens', 'tu aimes', 'tu penses quoi'],
        'de': ['wie fühlst du', 'hast du gefühle', 'magst du'],
        'ja': ['どう思う', '気持ち', '好きですか'],
        'ko': ['어때', '느낌이 어때', '좋아해'],
        'ru': ['как ты себя чувствуешь', 'у тебя есть чувства', 'тебе нравится'],
        'zh': ['你感觉怎么样', '你喜欢吗', '你觉得'],
    }

    # Multi-language patterns for CONTROL commands
    CONTROL_PATTERNS = {
        'es': ['resume', 'resumen', 'traduce', 'traducir', 'más corto', 'explica simple', 'en inglés'],
        'en': ['summarize', 'summary', 'translate', 'shorter', 'explain simply', 'in spanish'],
        'fr': ['résume', 'traduis', 'plus court'],
        'de': ['zusammenfassung', 'übersetze', 'kürzer'],
        'ja': ['要約', '翻訳', '短く'],
        'ko': ['요약', '번역', '짧게'],
        'ru': ['резюме', 'переведи', 'короче'],
        'zh': ['总结', '翻译', '简短'],
    }

    # Multi-language patterns for PERSONAL_KB (user's documents/notes)
    PERSONAL_KB_PATTERNS = {
        'es': ['mis notas', 'mis apuntes', 'los apuntes', 'las notas', 'el documento',
               'en el pdf', 'en mi repo', 'mis archivos', 'los archivos',
               'según mis', 'según el', 'mi setup', 'el error que me dio', 'en mi documento',
               'revisa el', 'revisa los', 'busca en el', 'busca en los',
               'en el archivo', 'del pdf', 'del documento', 'de los apuntes'],
        'en': ['my notes', 'the notes', 'in my notes', 'in the notes', 'in the pdf',
               'in my repo', 'my files', 'the files', 'the document',
               'according to my', 'according to the', 'my setup', 'the error i got',
               'in my document', 'in the document',
               'check the', 'search in the', 'from the pdf', 'from the document', 'from the notes'],
        'fr': ['mes notes', 'les notes', 'dans le pdf', 'mon repo', 'mes fichiers',
               'les fichiers', 'selon mes', 'selon le',
               'vérifie le', 'cherche dans le', 'du pdf', 'du document'],
        'de': ['meine notizen', 'die notizen', 'im pdf', 'mein repo', 'meine dateien',
               'die dateien', 'laut meinen', 'laut dem',
               'prüfe die', 'suche in den', 'aus dem pdf', 'aus dem dokument'],
        'ja': ['私のノート', 'ノート', 'PDFで', '私のファイル', 'ファイル', '私のリポジトリ',
               'ドキュメント', 'PDFから', 'ノートから'],
        'ko': ['내 노트', '노트', 'PDF에서', '내 파일', '파일', '내 저장소',
               '문서', 'PDF에서', '노트에서'],
        'ru': ['мои заметки', 'заметки', 'в pdf', 'мои файлы', 'файлы', 'мой репозиторий',
               'в моих', 'в документе', 'из pdf', 'из документа'],
        'zh': ['我的笔记', '笔记', '在PDF里', '我的文件', '文件', '我的仓库',
               '根据我的', '在文档里', '从PDF', '从文档'],
    }

    def __init__(self):
        """Initialize intent classifier."""
        self.lang_detector = SimpleLanguageDetector()
        log.info("Initialized IntentClassifier with multi-language support")

    def classify(self, query: str) -> IntentType:
        """Classify query intent for routing decisions.

        Args:
            query: User query string.

        Returns:
            Intent type: SMALL_TALK, PERSONAL_CHAT, CONTROL, GENERAL_KNOWLEDGE, or PERSONAL_KB
        """
        query_lower = query.lower().strip()
        query_len = len(query)

        # Detect language hint
        lang_hint = self.lang_detector.detect_language_hint(query) or 'en'

        log.debug("Classifying intent: query='%s' (len=%d, lang_hint=%s)",
                 query[:50], query_len, lang_hint)

        # Step 1: Check for PERSONAL_KB patterns (highest priority)
        # These indicate explicit reference to user's documents
        if self._match_patterns(query_lower, self.PERSONAL_KB_PATTERNS, lang_hint):
            log.info("Intent: PERSONAL_KB (references user documents)")
            return "PERSONAL_KB"

        # Step 2: Check for SMALL_TALK (greetings, thanks, simple affirmations)
        # Very short queries (<= 20 chars) with known patterns
        if query_len <= 20:
            if self._match_patterns(query_lower, self.GREETINGS, lang_hint):
                log.info("Intent: SMALL_TALK (greeting)")
                return "SMALL_TALK"
            if self._match_patterns(query_lower, self.THANKS, lang_hint):
                log.info("Intent: SMALL_TALK (thanks)")
                return "SMALL_TALK"
            if self._match_patterns(query_lower, self.GOODBYES, lang_hint):
                log.info("Intent: SMALL_TALK (goodbye)")
                return "SMALL_TALK"

        # Step 3: Check for affirmations/negations (conversational noise)
        if query_len <= 30:
            if self._match_patterns(query_lower, self.AFFIRMATIONS, lang_hint):
                log.info("Intent: SMALL_TALK (affirmation)")
                return "SMALL_TALK"
            if self._match_patterns(query_lower, self.NEGATIONS, lang_hint):
                log.info("Intent: SMALL_TALK (negation)")
                return "SMALL_TALK"

        # Step 4: Check for PERSONAL_CHAT (bot identity/feelings)
        # Questions about the bot itself, not about documents
        if query_len <= 50:
            if self._match_patterns(query_lower, self.BOT_NAME_PATTERNS, lang_hint):
                log.info("Intent: PERSONAL_CHAT (bot name/identity)")
                return "PERSONAL_CHAT"
            if self._match_patterns(query_lower, self.BOT_FEELINGS_PATTERNS, lang_hint):
                log.info("Intent: PERSONAL_CHAT (bot feelings/opinions)")
                return "PERSONAL_CHAT"

        # Step 5: Check for CONTROL commands
        if self._match_patterns(query_lower, self.CONTROL_PATTERNS, lang_hint):
            log.info("Intent: CONTROL (format/style command)")
            return "CONTROL"

        # Step 6: Default to GENERAL_KNOWLEDGE
        # Informational queries that don't reference user's documents
        log.info("Intent: GENERAL_KNOWLEDGE (default for informational queries)")
        return "GENERAL_KNOWLEDGE"

    def _match_patterns(self, query_lower: str, pattern_dict: dict, lang_hint: str) -> bool:
        """Check if query matches any pattern for the detected language.

        Args:
            query_lower: Lowercased query.
            pattern_dict: Dict of {lang: [patterns]}.
            lang_hint: Detected language hint.

        Returns:
            True if any pattern matches.
        """
        # Check patterns for detected language
        if lang_hint in pattern_dict:
            for pattern in pattern_dict[lang_hint]:
                if pattern in query_lower:
                    return True

        # Fallback: check all languages if no match in detected language
        # (handles multilingual queries and misdetection)
        for patterns in pattern_dict.values():
            for pattern in patterns:
                if pattern in query_lower:
                    return True

        return False

    def should_use_rag(self, intent: IntentType) -> bool:
        """Determine if RAG retrieval should be used for this intent.

        Args:
            intent: Classified intent type.

        Returns:
            True if RAG should be used, False otherwise.
        """
        # Use RAG for PERSONAL_KB (explicit references) and GENERAL_KNOWLEDGE (try RAG first)
        # Skip RAG only for SMALL_TALK, PERSONAL_CHAT, and CONTROL
        return intent in ("PERSONAL_KB", "GENERAL_KNOWLEDGE")


__all__ = ["IntentClassifier", "IntentType"]
