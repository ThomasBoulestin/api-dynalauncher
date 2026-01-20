# 🔧 Correctifs Appliqués - API DynaLauncher

## 📅 Date: 20 Janvier 2026

---

## 🚨 Problèmes Identifiés et Corrigés

### ❌ PROBLÈME #1: Watchdog Principal Désactivé (CRITIQUE)

**Symptôme:** Jobs "fantômes" restant actifs sans lien avec le launcher

**Cause:** Le thread `job_watchdog_task` était commenté et jamais démarré

```python
# # configure a watchdog thread  ← COMMENTÉ !
# watchdog = Thread(...)
```

**✅ Correction:** Réactivé le watchdog

```python
# Configure a watchdog thread to monitor dead processes
watchdog = Thread(
    target=job_watchdog_task, name="job_watchdog_task", args=[self], daemon=True
)
watchdog.start()
```

**Impact:** Le watchdog vérifie maintenant toutes les 5 secondes si les processus sont morts et nettoie automatiquement.

---

### ❌ PROBLÈME #2: Récupération du PID Non Fiable

**Symptôme:** Le launcher perd le contact avec le job LS-DYNA

**Cause:**

1. Sleep de 1 seconde trop court
2. Heuristique `len(children)==2` fragile et non documentée
3. Récupération du PID de `cmd.exe` au lieu du vrai processus LS-DYNA

**Arbre processus typique:**

```
cmd.exe (PID: 1234)              ← Mauvais PID récupéré avant !
└─ mpiexec.exe (PID: 5678)
   └─ pmi_proxy.exe
      └─ ls-dyna_dp_x64.exe (PID: 9012)  ← Le bon PID
```

**✅ Correction:**

- Retry jusqu'à 10 secondes pour trouver le processus
- Recherche par nom de processus (ls-dyna, lsdyna, dyna, mpp)
- Logging détaillé pour diagnostic

```python
# Retry logic: wait up to 10 seconds for LS-DYNA process to start
for attempt in range(20):  # 20 attempts x 0.5s = 10 seconds max
    sleep(0.5)
    # Search for LS-DYNA process by name pattern
    for p in children:
        proc_name = p.name().lower()
        if any(name in proc_name for name in ['ls-dyna', 'lsdyna', 'dyna', 'mpp']):
            pid_to_write = p.pid
            break
```

---

### ❌ PROBLÈME #3: Gestion d'Erreurs Masquées

**Symptôme:** Erreurs silencieuses, difficile à débugger

**Cause:** Blocs `except:` sans spécifier le type d'exception

```python
except:
    pass  # Masque TOUTES les erreurs !
```

**✅ Correction:** Logging explicite des erreurs

```python
except Exception as e:
    print(
        Fore.RED +
        f"ERROR: Failed to commit database for job {self.sq_job.id}: {e}" +
        Style.RESET_ALL
    )
```

---

### ❌ PROBLÈME #4: Pas de Moyen de Nettoyer les Processus Orphelins

**Symptôme:** Processus LS-DYNA restent actifs et bloquent les licences

**✅ Correction:** Nouvelle fonction `kill_orphan_dyna_processes()`

Ajout de 2 nouvelles méthodes dans l'API WebSocket:

#### 1. `killOrphanDynaProcesses(working_dir=None)`

Tue les processus LS-DYNA orphelins

**Exemple d'appel depuis le client:**

```javascript
{
  "jsonrpc": "2.0",
  "method": "killOrphanDynaProcesses",
  "params": {},
  "id": 1
}
```

**Réponse:**

```javascript
{
  "jsonrpc": "2.0",
  "result": {
    "killed_count": 3,
    "message": "Killed 3 orphan LS-DYNA process(es)"
  },
  "id": 1
}
```

#### 2. `getCoreAllocationStatus()`

Voir l'état d'allocation des cores CPU

---

## 📊 Améliorations Détaillées

### 1. Récupération PID Robuste

**Avant:**

- ⏱️ Wait: 1 seconde (fixe)
- 🔍 Méthode: Heuristique `len(children)==2`
- ⚠️ Fallback: Garde le mauvais PID
- 📝 Logging: "noprocess" (pas d'info)

**Après:**

- ⏱️ Wait: Jusqu'à 10 secondes avec retry
- 🔍 Méthode: Recherche par nom de processus
- ⚠️ Fallback: Log les processus disponibles pour debug
- 📝 Logging: Détaillé avec couleurs

### 2. Watchdog Actif

**Vérifie toutes les 5 secondes:**

- ✅ Si le PID existe toujours (`psutil.pid_exists()`)
- ✅ Si le thread watchdog est vivant
- ✅ Si le statut est terminal mais processus toujours actif

**Actions automatiques:**

- 🔄 Change le statut à "Stopped" si processus mort
- 🧹 Nettoie le job du manager
- 🔓 Libère les cores CPU alloués

### 3. Fonction de Nettoyage

```python
def kill_orphan_dyna_processes(working_dir: str = None) -> int:
    """Kill orphan LS-DYNA processes that are no longer tracked"""
```

**Fonctionnalités:**

- 🔍 Détecte tous les processus LS-DYNA actifs
- 📂 Peut filtrer par répertoire de travail (optionnel)
- 🔫 Tue les processus orphelins
- 📊 Retourne le nombre de processus tués

---

## 🎯 Comment Tester les Corrections

### Test 1: Vérifier le Watchdog

1. Lancez un job
2. Tuez manuellement le processus LS-DYNA (Task Manager)
3. **Attendez 5-10 secondes**
4. ✅ Le job devrait passer en statut "Stopped" automatiquement

### Test 2: Vérifier la Récupération du PID

1. Lancez un job
2. Regardez les logs console du serveur
3. ✅ Vous devriez voir: `Found LS-DYNA process: ls-dyna_dp_x64.exe (PID: XXXX)`
4. ❌ Si vous voyez: `ERROR: Could not find LS-DYNA process` → Adapter les noms de processus

### Test 3: Nettoyer les Processus Orphelins

1. Créez un job fantôme (arrêtez le launcher pendant un job)
2. Redémarrez le launcher
3. Appelez `killOrphanDynaProcesses()` depuis le client
4. ✅ Les processus orphelins doivent être tués

### Test 4: Vérifier l'Allocation des Cores

1. Appelez `getCoreAllocationStatus()`
2. ✅ Vérifiez que les cores sont correctement alloués/libérés

---

## ⚙️ Configuration Recommandée

### Noms de Processus LS-DYNA

Si vos exécutables LS-DYNA ont des noms différents, modifiez cette ligne:

**Fichier:** `serv/job_manager.py` ligne ~641

```python
if any(name in proc_name for name in ['ls-dyna', 'lsdyna', 'dyna', 'mpp']):
```

Ajoutez vos noms de processus à la liste.

### Timeout de Démarrage

Par défaut: 10 secondes (20 tentatives x 0.5s)

Pour modifier (ligne ~636):

```python
for attempt in range(20):  # Changez 20 si nécessaire
    sleep(0.5)  # Changez 0.5 si nécessaire
```

---

## 🐛 Debugging

### Logs à Surveiller

**Démarrage réussi:**

```
Found LS-DYNA process: ls-dyna_dp_x64.exe (PID: 12345)
Job - 1 Started
```

**Problème de PID:**

```
ERROR: Could not find LS-DYNA process for job 1. Using fallback PID: 5678
Available child processes: [(5678, 'mpiexec.exe'), (9012, 'pmi_proxy.exe')]
```

→ Adapter la liste des noms de processus

**Processus mort détecté:**

```
Warning: Not alive job 1 detected, stopping...
Job - 1 Stopped
Released cores 0-7 from job 1
```

---

## 📝 Changements API WebSocket

### Nouvelles Méthodes

#### `killOrphanDynaProcesses`

**Paramètres:**

- `working_dir` (optionnel): Chemin du répertoire de travail

**Retour:**

```json
{
  "killed_count": 2,
  "message": "Killed 2 orphan LS-DYNA process(es)"
}
```

#### `getCoreAllocationStatus`

**Paramètres:** Aucun

**Retour:**

```json
{
  "physical_cores": 8,
  "logical_cores": 16,
  "hyper_threading_enabled": true,
  "available_cores": 8,
  "cores": [
    {"index": 0, "job_id": 1, "pid": 12345},
    {"index": 1, "job_id": 1, "pid": 12345},
    {"index": 2, "job_id": null, "pid": null},
    ...
  ]
}
```

---

## ⚠️ Points d'Attention

### 1. CREATE_BREAKAWAY_FROM_JOB

Le flag `CREATE_BREAKAWAY_FROM_JOB` permet aux processus de survivre si le launcher crash.

**Avantages:** ✅ Jobs continuent en cas de crash du launcher
**Inconvénients:** ⚠️ Peut créer des orphelins

**Recommandation:** Garder ce flag mais utiliser `killOrphanDynaProcesses()` régulièrement

### 2. Performance du Watchdog

Le watchdog vérifie tous les jobs toutes les 5 secondes. Si vous avez beaucoup de jobs (>50), considérez augmenter l'intervalle.

**Modifier ligne ~544:**

```python
sleep(5)  # Changez à 10 ou 15 si beaucoup de jobs
```

### 3. Licences LS-DYNA

Les licences sont libérées quand:

1. Le processus se termine normalement
2. Le watchdog détecte un processus mort
3. Vous appelez `killOrphanDynaProcesses()`

Si les licences restent bloquées, vérifiez votre serveur de licences LSTC.

---

## 🚀 Prochaines Améliorations Possibles

### Recommandation 1: Logging Professionnel

Remplacer `print()` par le module `logging`:

```python
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"Job {job_id} started")
logger.error(f"Failed to find PID for job {job_id}")
```

### Recommandation 2: Health Check Endpoint

Ajouter une méthode pour vérifier l'état global:

```python
@method
def getSystemHealth():
    return {
        "running_jobs": len(job_manager.jobs),
        "watchdog_active": watchdog.is_alive(),
        "orphan_processes": count_orphan_processes()
    }
```

### Recommandation 3: Auto-Cleanup au Démarrage

Nettoyer les processus orphelins automatiquement au démarrage du launcher:

```python
# Dans set_context():
orphans = kill_orphan_dyna_processes()
if orphans > 0:
    print(f"Cleaned {orphans} orphan process(es) at startup")
```

---

## 📞 Support

En cas de problème:

1. Vérifiez les logs console du serveur
2. Testez avec `--noIntelMpiCoreAllocation` pour isoler les problèmes de cores
3. Utilisez `getCoreAllocationStatus()` pour voir l'état des allocations
4. Appelez `killOrphanDynaProcesses()` si nécessaire

---

## ✅ Checklist de Validation

- [ ] Watchdog détecte les processus morts en <10 secondes
- [ ] Le bon PID (LS-DYNA) est récupéré au démarrage
- [ ] Les licences sont libérées quand un job se termine
- [ ] Pas de jobs fantômes après un crash du launcher
- [ ] Les cores CPU sont correctement alloués et libérés
- [ ] `killOrphanDynaProcesses()` fonctionne depuis le client
- [ ] Logs détaillés permettent le debugging

---

**Version:** 2.0.9+fixes
**Fichiers Modifiés:**

- `serv/job_manager.py` (corrections majeures)
- `serv/websocket_api.py` (nouvelles méthodes)
