import re
from storage.db import get_repository_details, get_all_repositories, get_connection

TECH_PATTERNS = {
    "JavaScript": [r"\bjavascript\b", r"\bjs\b"],
    "TypeScript": [r"\btypescript\b", r"\bts\b"],
    "Python": [r"\bpython\b"],
    "React": [r"\breact\b", r"\breact\.js\b", r"\breactjs\b"],
    "React Native": [r"\breact native\b"],
    "Node.js": [r"\bnode\.js\b", r"\bnodejs\b", r"\bnode\b"],
    "Express.js": [r"\bexpress\.js\b", r"\bexpressjs\b", r"\bexpress\b"],
    "MongoDB": [r"\bmongodb\b", r"\bmongo\b"],
    "FastAPI": [r"\bfastapi\b"],
    "PostgreSQL": [r"\bpostgresql\b", r"\bpostgres\b"],
    "TailwindCSS": [r"\btailwindcss\b", r"\btailwind\b"],
    "Docker": [r"\bdocker\b"],
    "Kafka": [r"\bkafka\b"],
    "Redis": [r"\bredis\b"],
    "Plotly": [r"\bplotly\b"],
    "Gemini": [r"\bgemini\b"],
    "Groq": [r"\bgroq\b"],
    "Next.js": [r"\bnext\.js\b", r"\bnextjs\b"],
    "Firebase": [r"\bfirebase\b"],
    "SQLite": [r"\bsqlite\b", r"\bsqlite3\b"]
}

# Compile patterns for faster regex scanning
COMPILED_PATTERNS = {
    tech: [re.compile(p, re.IGNORECASE) for p in patterns]
    for tech, patterns in TECH_PATTERNS.items()
}

def detect_tech_in_text(text: str) -> list:
    if not text:
        return []
    detected = []
    for tech, patterns in COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                detected.append(tech)
                break
    return detected

def detect_tech_for_repo(repo_name: str) -> list:
    details = get_repository_details(repo_name)
    if not details:
        return []
    
    contents = []
    if details.get("description"):
        contents.append(details["description"])
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)", (repo_name,))
    for row in cursor.fetchall():
        if row[0]:
            contents.append(row[0])
    conn.close()
    
    combined_text = "\n".join(contents)
    detected = detect_tech_in_text(combined_text)
    return sorted(list(set(detected)))

def detect_all_tech() -> list:
    repos = get_all_repositories()
    all_tech = set()
    for repo in repos:
        tech_list = detect_tech_for_repo(repo["repo_name"])
        all_tech.update(tech_list)
    return sorted(list(all_tech))

def find_repos_by_tech(tech_name: str) -> list:
    repos = get_all_repositories()
    matching_repos = []
    tech_name_lower = tech_name.lower()
    
    for repo in repos:
        repo_name = repo["repo_name"]
        detected = detect_tech_for_repo(repo_name)
        
        has_match = False
        for t in detected:
            if t.lower() == tech_name_lower:
                has_match = True
                break
                
        if not has_match:
            # Fallback direct substring/regex lookup in full text
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT content FROM repository_documents WHERE LOWER(repo_name) = LOWER(?)", (repo_name,))
            combined_text = (repo.get("description") or "") + "\n" + "\n".join([row[0] for row in cursor.fetchall() if row[0]])
            conn.close()
            
            if re.search(r'\b' + re.escape(tech_name_lower) + r'\b', combined_text.lower()):
                has_match = True
                
        if has_match:
            matching_repos.append(repo_name)
            
    return sorted(matching_repos)
