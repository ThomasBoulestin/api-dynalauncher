# 🔧 CORRECTIFS URGENTS APPLIQUÉS

## ⚡ Actions Immédiates

### 1. ✅ WATCHDOG RÉACTIVÉ (CRITIQUE)

Le watchdog qui surveille les processus morts a été **réactivé**.

- **Ligne modifiée:** `serv/job_manager.py` L391-395
- **Impact:** Détection automatique des jobs fantômes toutes les 5 secondes

### 2. ✅ RÉCUPÉRATION PID AMÉLIORÉE (CRITIQUE)

Nouvelle logique robuste pour trouver le bon processus LS-DYNA:

- **Retry:** jusqu'à 10 secondes (au lieu de 1s)
- **Méthode:** Recherche par nom de processus (au lieu d'heuristique fragile)
- **Logging:** Détaillé pour diagnostic

### 3. ✅ FONCTION DE NETTOYAGE AJOUTÉE

Nouvelle méthode API: `killOrphanDynaProcesses()`

- Tue les processus LS-DYNA orphelins
- Libère les licences bloquées
- Utilisable depuis le client WebSocket

### 4. ✅ MEILLEUR LOGGING

Remplacement des `except: pass` par des logs explicites

---

## 🧪 Tests à Faire

### Test Rapide

```bash
# Lancer le serveur
python server.py

# Lancer les tests
python test_correctifs.py
```

### Test Complet (avec vrai job)

1. Lancez un job LS-DYNA
2. Vérifiez dans les logs: `Found LS-DYNA process: xxx (PID: xxx)`
3. Tuez le processus manuellement (Task Manager)
4. Attendez 5-10 secondes
5. **Résultat attendu:** Le job passe automatiquement en "Stopped"

---

## 📡 Nouvelles Méthodes API

### killOrphanDynaProcesses

```json
{
  "jsonrpc": "2.0",
  "method": "killOrphanDynaProcesses",
  "params": {},
  "id": 1
}
```

### getCoreAllocationStatus

```json
{
  "jsonrpc": "2.0",
  "method": "getCoreAllocationStatus",
  "params": {},
  "id": 2
}
```

---

## 🔍 Diagnostic

### Logs à Surveiller

**✅ Bon:**

```
Found LS-DYNA process: ls-dyna_dp_x64.exe (PID: 12345)
Job - 1 Started
```

**❌ Mauvais:**

```
ERROR: Could not find LS-DYNA process for job 1
Available child processes: [...]
```

→ Adapter les noms de processus dans le code

---

## 📝 Fichiers Modifiés

1. **serv/job_manager.py**

   - Watchdog réactivé
   - Récupération PID améliorée
   - Fonction `kill_orphan_dyna_processes()`
   - Meilleur logging

2. **serv/websocket_api.py**

   - Import de `kill_orphan_dyna_processes`
   - Méthode `killOrphanDynaProcesses()`
   - Méthode `getCoreAllocationStatus()`

3. **CORRECTIFS_APPLIQUES.md** (nouveau)

   - Documentation complète

4. **test_correctifs.py** (nouveau)
   - Suite de tests

---

## ⚠️ Important

Si vos exécutables LS-DYNA ont des **noms différents**, modifiez cette ligne:

**Fichier:** `serv/job_manager.py` ligne ~641

```python
if any(name in proc_name for name in ['ls-dyna', 'lsdyna', 'dyna', 'mpp']):
    # Ajoutez vos noms ici ↑
```

---

## 🆘 En Cas de Problème

1. Vérifiez les logs console du serveur
2. Lancez `python test_correctifs.py`
3. Testez avec `--noIntelMpiCoreAllocation` pour isoler les problèmes
4. Appelez `killOrphanDynaProcesses()` pour nettoyer

---

**Date:** 20 janvier 2026  
**Version:** 2.0.9+fixes
