import os
import re

src_dir = r"C:\Users\betaj\Documents\Projeto retorica"
dest_dir = r"C:\Users\betaj\Documents\Projeto filopaluza"

files = ["sugestoes.html", "enquetes.html", "repertorio.html", "logs.html"]

def adapt_content(content, filename):
    # Base replacements
    content = content.replace("Retórica", "Filópaluza")
    content = content.replace("retorica", "filopaluza")
    content = content.replace("🎸", "🤠")
    content = content.replace("imagens/Toca_do_Mineiro_logo_final.png", "imagens/filopaluza_logo.png")
    content = content.replace('content="#0a0804"', 'content="#0D0805"')
    content = content.replace('https://us-central1-filopaluza-b05b3.cloudfunctions.net', 'https://us-central1-filopaluza.cloudfunctions.net') # because it replaced retorica->filopaluza
    
    # Remove coins from HTML
    content = re.sub(r'<a href="index\.html" class="coin-balance".*?</a>', '', content)
    
    # Remove audit, galeria, setlist from nav
    content = re.sub(r'<li[^>]*><a href="setlist\.html".*?</a></li>\n*', '', content)
    content = re.sub(r'<li[^>]*><a href="galeria\.html".*?</a></li>\n*', '', content)
    content = re.sub(r'<li class="audit-admin-only".*?</li>\n*', '', content)
    content = re.sub(r'<a href="setlist\.html".*?</a>\n*', '', content)
    content = re.sub(r'<a href="galeria\.html".*?</a>\n*', '', content)
    content = re.sub(r'<a href="audit\.html".*?</a>\n*', '', content)
    
    # Remove coin logic from applyAuth
    coin_logic_regex = r"if \(isLoggedIn && isMember && auth\.currentUser\) \{.*?else \{[^\}]+\}"
    content = re.sub(coin_logic_regex, "", content, flags=re.DOTALL)
    
    if filename == "repertorio.html":
        # Remove setlist buttons in repertorio
        content = re.sub(r'<button class="btn-ghost btn-sm" id="repFilterSetlist".*?</button>', '', content)
        content = re.sub(r'<button class="btn-ghost btn-sm" onclick="importSetlistToRep\(\)".*?</button>', '', content)
        content = re.sub(r'const NEXT_SETLIST_KEY.*?;', '', content)
        content = re.sub(r'const LEGACY_SETLIST_KEY.*?;', '', content)
        content = re.sub(r'let setlistData.*?;', '', content)
        content = re.sub(r'let setlistLoaded.*?;', '', content)
        
        # We can't safely regex out whole JS functions, but we can replace their body with empty or let them be dead code.
        # Let's remove the "in-setlist" UI elements:
        content = re.sub(r'\$\{inSetlist\s*\?\s*`<div class="rep-setlist-tag".*?</div>`\s*:\s*\'\'\}', '', content)
        content = re.sub(r'\$\{isMember\s*\?\s*`<button class="btn-ghost btn-sm" onclick="addRepToSetlist.*?<\/button>`\s*:\s*\'\'\}', '', content)

    if filename == "logs.html":
        # Remove setlist, galeria, forum filters from logs.html
        content = re.sub(r'<button class="log-filter-btn" data-f="setlist">Setlist</button>', '', content)
        content = re.sub(r'<button class="log-filter-btn" data-f="galeria">Galeria</button>', '', content)
        content = re.sub(r'<button class="log-filter-btn" data-f="forum">Fórum</button>', '', content)
        
        # Remove audit notice
        content = re.sub(r'<div class="audit-tools-notice".*?</div>', '', content, flags=re.DOTALL)
        
        # Remove storage stats panel
        content = re.sub(r'<div id="storageStatsPanel".*?</div>\s*</div>\s*</div>', '', content, flags=re.DOTALL)
        
        # Remove member stats coin panel
        content = re.sub(r'<div class="part-stat-card">.*?Retorica Coin.*?</div>', '', content, flags=re.DOTALL)
        content = re.sub(r'<div class="part-stat-card">.*?Streak Atual.*?</div>', '', content, flags=re.DOTALL)
        content = re.sub(r'<div class="part-stat-card">.*?Maior Streak.*?</div>', '', content, flags=re.DOTALL)
        
        # Remove firebase inline config since it still uses Retórica's.
        # Actually logs.html should use the same firebase-init.js for simplicity, let's inject it.
        # Find the inline firebase config and replace it.
        inline_firebase_regex = r'import \{ initializeApp \} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";.*?const db = getFirestore\(app\);'
        replacement = r'''import {
  db, auth, collection, doc, getDoc, getDocs, onSnapshot, query, orderBy, limit, deleteDoc, updateDoc, writeBatch
} from "./firebase-init.js";
const { onAuthStateChanged, signOut } = await import("https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js");'''
        content = re.sub(inline_firebase_regex, replacement, content, flags=re.DOTALL)

    return content

for filename in files:
    src_path = os.path.join(src_dir, filename)
    dest_path = os.path.join(dest_dir, filename)
    
    with open(src_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    adapted = adapt_content(content, filename)
    
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(adapted)

print("Files adapted successfully!")
