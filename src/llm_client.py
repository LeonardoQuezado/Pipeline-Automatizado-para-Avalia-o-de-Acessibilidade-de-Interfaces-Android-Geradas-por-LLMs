import asyncio
import os
import time
from pathlib import Path
from typing import Dict, Optional
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from google import genai
from dotenv import load_dotenv

load_dotenv()

class LLMClient:
    def __init__(self):
        # Gemini (obrigatório)
        self.gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        # Groq, OpenAI e Anthropic (opcionais, requerem chave)
        self.groq_key      = os.getenv("GROQ_API_KEY")
        self.deepseek_key  = os.getenv("DEEPSEEK_API_KEY")
        self.xai_key       = os.getenv("XAI_API_KEY")
        self.openai_key    = os.getenv("OPENAI_API_KEY")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")

        self.groq = AsyncOpenAI(
            api_key=self.groq_key,
            base_url="https://api.groq.com/openai/v1",
        ) if self.groq_key else None
        self.deepseek = AsyncOpenAI(
            api_key=self.deepseek_key,
            base_url="https://api.deepseek.com/v1",
        ) if self.deepseek_key else None
        self.xai = AsyncOpenAI(
            api_key=self.xai_key,
            base_url="https://api.x.ai/v1",
        ) if self.xai_key else None
        self.openai    = AsyncOpenAI(api_key=self.openai_key) if self.openai_key else None
        self.anthropic = AsyncAnthropic(api_key=self.anthropic_key) if self.anthropic_key else None

        # Ollama (local) — conecta via API compatível com OpenAI
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        self.ollama_model    = os.getenv("OLLAMA_MODEL", "llama3.2")
        self.ollama = AsyncOpenAI(
            base_url=f"{self.ollama_base_url}/v1",
            api_key="ollama",          # exigido pelo SDK, mas não validado pelo Ollama
        )

        self._print_enabled_llms()

    def _print_enabled_llms(self):
        print("\n" + "=" * 50)
        print("LLMs enabled:")
        print("=" * 50)
        print("[enabled]  Gemini (free)")
        if self.groq:
            print("[enabled]  Groq (free tier — llama-3.3-70b-versatile)")
        else:
            print("[disabled] Groq (no API key)")
        if self.deepseek:
            print("[enabled]  DeepSeek (deepseek-coder)")
        else:
            print("[disabled] DeepSeek (no API key)")
        if self.xai:
            print("[enabled]  xAI Grok (grok-3-mini)")
        else:
            print("[disabled] xAI Grok (no API key)")
        if self.openai:
            print("[enabled]  OpenAI (paid)")
        else:
            print("[disabled] OpenAI (no API key)")
        if self.anthropic:
            print("[enabled]  Anthropic Claude (paid)")
        else:
            print("[disabled] Anthropic Claude (no API key)")
        print(f"[local]    Ollama — model: {self.ollama_model} @ {self.ollama_base_url}")
        print("=" * 50 + "\n")
    
    async def generate_gemini(self, prompt: str) -> str:
        """Gemini — retries up to 3x on transient 503/UNAVAILABLE errors."""
        loop = asyncio.get_running_loop()
        max_attempts = 3
        for attempt in range(max_attempts):
            if attempt == 0:
                print("Calling Gemini...")
            else:
                print(f"Calling Gemini (retry {attempt}/{max_attempts - 1})...")
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: self.gemini_client.models.generate_content(
                        model='gemini-2.5-pro',
                        contents=prompt
                    )
                )
                return response.text
            except Exception as e:
                err = str(e)
                is_transient = any(w in err for w in ("503", "UNAVAILABLE", "529", "overloaded"))
                if is_transient and attempt < max_attempts - 1:
                    wait = 5 * (2 ** attempt)   # 5s, 10s
                    print(f"  Gemini unavailable — retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise
    
    async def generate_groq(self, prompt: str) -> str:
        """Groq — API gratuita, modelo llama-3.3-70b-versatile (rápido)."""
        if not self.groq:
            return "SKIPPED"
        print("Calling Groq (llama-3.3-70b-versatile)...")
        response = await self.groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )
        return response.choices[0].message.content

    async def generate_deepseek(self, prompt: str) -> str:
        """DeepSeek Coder — especializado em código."""
        if not self.deepseek:
            return "SKIPPED"
        print("Calling DeepSeek (deepseek-coder)...")
        response = await self.deepseek.chat.completions.create(
            model="deepseek-coder",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )
        return response.choices[0].message.content

    async def generate_xai(self, prompt: str) -> str:
        """xAI Grok — grok-3-mini (créditos $25 gratuitos no cadastro)."""
        if not self.xai:
            return "SKIPPED"
        print("Calling xAI Grok (grok-3-mini)...")
        response = await self.xai.chat.completions.create(
            model="grok-3-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )
        return response.choices[0].message.content

    async def generate_openai(self, prompt: str) -> str:
        """OpenAI ChatGPT 5.5 — used in the WebMedia 2026 evaluation."""
        if not self.openai:
            return "SKIPPED"
        print("Calling OpenAI (ChatGPT 5.5)...")
        response = await self.openai.chat.completions.create(
            model="gpt-4.5",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

    async def generate_anthropic(self, prompt: str) -> str:
        """Anthropic Claude Sonnet 4.6 — used in the WebMedia 2026 evaluation."""
        if not self.anthropic:
            return "SKIPPED"

        print("Calling Anthropic Claude Sonnet 4.6...")
        response = await self.anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    async def generate_ollama(self, prompt: str) -> str:
        """Ollama — LLM local (API compatível com OpenAI)"""
        print(f"Calling Ollama ({self.ollama_model})...")
        try:
            response = await self.ollama.chat.completions.create(
                model=self.ollama_model,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except Exception as e:
            msg = str(e).lower()
            if any(w in msg for w in ("connection", "refused", "connect", "unreachable")):
                print(f"[SKIP] Ollama unavailable ({self.ollama_base_url})")
                return "SKIPPED"
            raise

    async def generate_all(self, prompt: str) -> Dict[str, str]:
        """Gera código com todas as LLMs habilitadas em paralelo."""
        enabled = set(os.getenv("ENABLED_LLMS", "").split(",")) - {""}
        candidates = {
            "gemini":    self.generate_gemini,
            "groq":      self.generate_groq,
            "deepseek":  self.generate_deepseek,
            "xai":       self.generate_xai,
            "openai":    self.generate_openai,
            "anthropic": self.generate_anthropic,
            "ollama":    self.generate_ollama,
        }
        tasks = {
            name: fn(prompt)
            for name, fn in candidates.items()
            if not enabled or name in enabled
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        output = dict(zip(tasks.keys(), results))
        return {k: v for k, v in output.items() if v != "SKIPPED"}

    async def generate_all_timed(self, prompt: str) -> Dict[str, tuple]:
        """Gera código em paralelo, retornando (resposta, tempo_s) por LLM.

        Returns: {llm_name: (response_or_Exception, elapsed_seconds)}
        LLMs desabilitadas (SKIPPED) são omitidas do resultado.
        """
        async def _timed(name: str, coro) -> tuple:
            t = time.perf_counter()
            try:
                result = await coro
                return name, result, time.perf_counter() - t
            except Exception as exc:
                return name, exc, time.perf_counter() - t

        # Respect ENABLED_LLMS env var (set by the web UI LLM selector)
        enabled = set(os.getenv("ENABLED_LLMS", "").split(",")) - {""}

        candidates = {
            "gemini":    self.generate_gemini,
            "groq":      self.generate_groq,
            "deepseek":  self.generate_deepseek,
            "xai":       self.generate_xai,
            "openai":    self.generate_openai,
            "anthropic": self.generate_anthropic,
            "ollama":    self.generate_ollama,
        }
        tasks = [
            _timed(name, fn(prompt))
            for name, fn in candidates.items()
            if not enabled or name in enabled
        ]
        raw = await asyncio.gather(*tasks)
        return {
            name: (resp, elapsed)
            for name, resp, elapsed in raw
            if resp != "SKIPPED"
        }
    
    async def generate_one(self, llm_name: str, prompt: str) -> str:
        """Call a single LLM by name. Raises ValueError if unknown or disabled."""
        generators: dict = {
            "gemini":    self.generate_gemini,
            "groq":      self.generate_groq,
            "deepseek":  self.generate_deepseek,
            "xai":       self.generate_xai,
            "openai":    self.generate_openai,
            "anthropic": self.generate_anthropic,
            "ollama":    self.generate_ollama,
        }
        fn = generators.get(llm_name)
        if fn is None:
            raise ValueError(f"Unknown LLM: {llm_name!r}")
        result = await fn(prompt)
        if result == "SKIPPED":
            raise ValueError(f"{llm_name} is not enabled")
        return result

    def save_codes(self, results: dict, output_dir: str = "/app/outputs/codes"):
        """Salva códigos gerados"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        for llm, code in results.items():
            if isinstance(code, Exception):
                print(f"❌ Erro no {llm}: {code}")
                continue
            
            file_path = output_path / f"{llm}_output.kt"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            print(f"✅ Código salvo: {file_path}")


if __name__ == "__main__":
    client = LLMClient()
    
    prompt = """Generate a complete Android Activity in Kotlin that:
    - Displays 'Hello World' in a TextView
    - Uses ViewBinding
    - Include all necessary imports
    - Only return the MainActivity.kt code, nothing else"""
    
    print("🚀 Gerando código com LLMs...\n")
    results = asyncio.run(client.generate_all(prompt))
    
    print("\n" + "="*50)
    print("📝 RESULTADOS")
    print("="*50)
    
    for llm, code in results.items():
        if isinstance(code, Exception):
            continue
        print(f"\n{'─'*50}")
        print(f"  {llm.upper()}")
        print(f"{'─'*50}")
        print(code[:300] + "..." if len(code) > 300 else code)
    
    client.save_codes(results)
    print("\n✅ Pipeline concluído!")