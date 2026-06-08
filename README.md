# 🤠 Guia de Configuração — Filópaluza

> Consulte o arquivo SETUP.md na raiz deste projeto para o roteiro completo.
> Abaixo está um resumo rápido.

## Início Rápido

### 1. Firebase
- Crie o projeto em console.firebase.google.com
- Ative: Authentication (Google), Firestore, Storage
- Copie o `firebaseConfig` → cole em `firebase-init.js`
- Adicione os 4 membros na coleção `approved_emails`:

| Document ID | name |
|---|---|
| juliocereser@gmail.com | Julio |
| vinitorressantos@gmail.com | Vini |
| rgmaia6@gmail.com | Roni |
| mfa200023@gmail.com | Matheus |

### 2. GitHub Pages
```bash
git init && git add . && git commit -m "setup inicial"
git remote add origin https://github.com/betajulio/filopaluza.git
git push -u origin main
```
No repo → Settings → Pages → Branch: main / root

**URL:** https://betajulio.github.io/filopaluza/

### 3. Cloud Functions (opcional — requer plano Blaze)
```bash
firebase deploy --only functions
```
Após o deploy, atualize `FUNCTIONS_BASE_URL` nos arquivos HTML.

---

## Estrutura do Projeto

```
Projeto filopaluza/
├── index.html          ← Home + Membros
├── sugestoes.html      ← Sugestões + votação
├── enquetes.html       ← Enquetes + promoção
├── repertorio.html     ← Repertório
├── logs.html           ← Admin
├── style.css           ← Tema sertanejo
├── firebase-init.js    ← ⚠ Coloque suas credenciais aqui
├── firestore.rules     ← Regras de segurança
├── functions/
│   ├── main.py         ← Cloud Functions Python
│   └── requirements.txt
└── imagens/
    └── filopaluza_logo.png
```
