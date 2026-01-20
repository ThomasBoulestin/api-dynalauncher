# 👻 Problème des Jobs "Fantômes" - Analyse Détaillée

## 🔍 Qu'est-ce qu'un Job Fantôme ?

Un job "fantôme" est un processus LS-DYNA qui:

- ✅ Est toujours **actif** dans Windows (visible dans Task Manager)
- ✅ Consomme une **licence LS-DYNA**
- ❌ N'est **plus tracé** par le launcher
- ❌ N'apparaît **plus** dans l'interface
- ❌ Ne peut **plus être contrôlé** (pas de stop possible)

**Résultat:** Licences bloquées, cores CPU occupés, impossible de relancer

---

## 🚨 Causes Identifiées

### 1. Watchdog Désactivé (Principal Coupable)

**Avant les correctifs:**

```python
# # configure a watchdog thread  ← COMMENTÉ !
# watchdog = Thread(...)
# watchdog.start()
```

**Conséquence:**

- Aucune surveillance des processus
- Si un processus meurt, personne ne le sait
- Si le launcher crash, les jobs deviennent orphelins

**Maintenant:**

```python
# Configure a watchdog thread to monitor dead processes
watchdog = Thread(
    target=job_watchdog_task, name="job_watchdog_task", args=[self], daemon=True
)
watchdog.start()  # ✅ ACTIF
```

Le watchdog vérifie **toutes les 5 secondes** si:

1. Le PID existe encore
2. Le thread de surveillance est vivant
3. Le statut correspond à l'état réel

---

### 2. Mauvais PID Capturé

**Arbre processus typique avec Intel MPI:**

```
┌─────────────────────────────────────────────────────┐
│ cmd.exe (PID: 1234)                                 │ ← Le launcher capture CE PID
│   ↓                                                  │    (qui meurt immédiatement)
│ mpiexec.exe (PID: 5678)      ← Hydra                │
│   ↓                                                  │
│ pmi_proxy.exe (PID: 9012)    ← PMI Proxy            │
│   ↓                                                  │
│ ls-dyna_dp_x64.exe (PID: 3456)  ← LE VRAI PROCESSUS│ ← On VEUT ce PID !
└─────────────────────────────────────────────────────┘
```

**Problème ancien:**

```python
process = subprocess.Popen("cmd /c " + command + "...")
pid_to_write = process.pid  # ← PID de cmd.exe (mauvais!)

# Heuristique fragile:
if len(p.children(recursive=True)) == 2:  # ← Pourquoi 2 ?!
    pid_to_write = p.pid
```

**Scénario du bug:**

1. `cmd.exe` démarre et obtient PID 1234
2. Le launcher enregistre PID 1234
3. `cmd.exe` lance `mpiexec` et **meurt immédiatement**
4. Le launcher surveille PID 1234 qui n'existe plus
5. `psutil.pid_exists(1234)` → `False`
6. Le launcher pense que le job est mort
7. **MAIS** `ls-dyna_dp_x64.exe` (PID 3456) tourne toujours !

**Solution appliquée:**

```python
# Retry jusqu'à 10 secondes
for attempt in range(20):
    sleep(0.5)

    # Chercher par NOM de processus (plus fiable)
    for p in children:
        proc_name = p.name().lower()
        if any(name in proc_name for name in ['ls-dyna', 'lsdyna', 'dyna', 'mpp']):
            pid_to_write = p.pid  # ← Le bon PID !
            break
```

---

### 3. CREATE_BREAKAWAY_FROM_JOB

```python
subprocess.Popen(
    command,
    creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NO_WINDOW
)
```

**Ce flag fait quoi ?**

- Permet au processus enfant de **survivre** si le parent meurt
- Le processus n'est **pas tué** quand le launcher crash

**Avantages:**

- ✅ Job continue si le launcher crash (utile!)
- ✅ Pas de perte de calcul en cours

**Inconvénients:**

- ❌ Crée des orphelins si mal géré
- ❌ Processus survivent même après arrêt du launcher

**Solution:**

- Garder le flag (utile pour la résilience)
- **MAIS** avoir un watchdog actif pour détecter les orphelins
- **ET** avoir `killOrphanDynaProcesses()` pour nettoyer

---

## 🔄 Cycle de Vie Normal d'un Job (Après Correctifs)

### 1. Démarrage

```
[Client] → startJob() → [Launcher]
                            ↓
                      Popen(command)
                            ↓
                    Attendre processus (10s max)
                            ↓
                    Trouver PID LS-DYNA
                            ↓
                    Enregistrer dans DB
                            ↓
                    Démarrer StdoutWatchdog
                            ↓
                    [Status: Starting → Running]
```

### 2. Surveillance (Pendant l'Exécution)

```
┌────────────────────────────────────────┐
│ StdoutWatchdogThread                   │ ← Lit stdout
│   - Parse progression (current/end)    │
│   - Détecte erreurs                    │
│   - Met à jour DB                      │
│   - Envoie via WebSocket               │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│ job_watchdog_task (toutes les 5s)     │ ← Surveille santé
│   - Vérifie psutil.pid_exists()       │
│   - Vérifie thread.is_alive()         │
│   - Détecte incohérences               │
│   - Nettoie jobs morts                 │
└────────────────────────────────────────┘
```

### 3. Fin Normale

```
[LS-DYNA termine] → "N o r m a l" dans stdout
                            ↓
                    StdoutWatchdog détecte
                            ↓
                    update_db(status="Finished")
                            ↓
                    release_cores()
                            ↓
                    WebSocket: notification client
```

### 4. Fin Anormale (Crash)

```
[Processus meurt] → psutil.pid_exists() = False
                            ↓
                    job_watchdog_task détecte
                            ↓
                    update_db(status="Stopped")
                            ↓
                    release_cores()
                            ↓
                    stop() thread watchdog
```

---

## 🛠️ Comment les Correctifs Résolvent le Problème

### Avant (État Bugué)

```
Job démarre → PID capturé incorrectement
    ↓
cmd.exe meurt → Launcher perd le lien
    ↓
ls-dyna continue → Plus de surveillance
    ↓
Licence bloquée → Job fantôme !
    ↓
Watchdog désactivé → Jamais détecté
```

### Après (Corrigé)

```
Job démarre → Recherche du vrai PID LS-DYNA (10s retry)
    ↓
PID trouvé → Enregistré dans DB + fichier pid
    ↓
Surveillance double:
  1. StdoutWatchdog → Progression
  2. job_watchdog_task → Santé processus
    ↓
Si processus meurt → Détecté en 5s max
    ↓
Nettoyage auto → Cores libérés, licence libérée
    ↓
Si orphelin quand même → killOrphanDynaProcesses()
```

---

## 📊 Comparaison Avant/Après

| Aspect               | AVANT                  | APRÈS                        |
| -------------------- | ---------------------- | ---------------------------- |
| **Watchdog actif**   | ❌ Non (commenté)      | ✅ Oui (toutes les 5s)       |
| **Récup. PID**       | ⚠️ Heuristique fragile | ✅ Recherche par nom         |
| **Timeout**          | ⚠️ 1 seconde fixe      | ✅ 10s avec retry            |
| **Détection mort**   | ❌ Jamais              | ✅ 5-10 secondes             |
| **Nettoyage manuel** | ❌ Impossible          | ✅ killOrphanDynaProcesses() |
| **Logging**          | ⚠️ "noprocess"         | ✅ Détaillé avec couleurs    |
| **Jobs fantômes**    | ❌ Fréquents           | ✅ Évités                    |

---

## 🧪 Tests de Validation

### Test 1: Détection Processus Mort

1. Lancez un job
2. **Immédiatement** tuez le processus LS-DYNA (Task Manager)
3. Attendez 5-10 secondes
4. **Résultat attendu:** Job passe en "Stopped", cores libérés

### Test 2: Récupération Bon PID

1. Lancez un job
2. Regardez les logs: doit afficher `Found LS-DYNA process: xxx (PID: xxx)`
3. Vérifiez dans Task Manager que le PID correspond à `ls-dyna*.exe`

### Test 3: Crash Launcher

1. Lancez un job
2. Tuez le launcher (Ctrl+C ou Task Manager)
3. Vérifiez que LS-DYNA continue (CREATE_BREAKAWAY fonctionne)
4. Redémarrez le launcher
5. Le job doit être reconnecté (si PID sauvegardé)
6. Sinon, utilisez `killOrphanDynaProcesses()` pour nettoyer

### Test 4: Nettoyage Orphelins

1. Créez des jobs fantômes (tuez launcher pendant jobs actifs)
2. Appelez `killOrphanDynaProcesses()` via WebSocket
3. Vérifiez dans Task Manager: plus de `ls-dyna*.exe`

---

## 💡 Recommandations Supplémentaires

### 1. Monitoring Proactif

Ajoutez un endpoint pour compter les orphelins:

```python
@method
def countOrphanProcesses():
    count = 0
    for proc in psutil.process_iter(['name']):
        if 'ls-dyna' in proc.info['name'].lower():
            count += 1
    return Success({"orphan_count": count})
```

### 2. Auto-Cleanup au Démarrage

Dans `set_context()`:

```python
# Nettoyer les orphelins au démarrage
orphans = kill_orphan_dyna_processes()
if orphans > 0:
    print(f"Cleaned {orphans} orphan LS-DYNA process(es) at startup")
```

### 3. Alertes Proactives

Envoyer une alerte WebSocket si un orphelin est détecté:

```python
if orphan_detected:
    socketio.emit("orphan_alert", {"count": orphan_count})
```

### 4. Logging dans Fichier

Remplacer `print()` par `logging` pour tracer l'historique:

```python
import logging
logging.basicConfig(filename='dynalauncher.log', level=logging.INFO)
```

---

## 🎯 Résumé

**Problème Principal:** Watchdog désactivé + Mauvais PID = Jobs Fantômes

**Solutions Appliquées:**

1. ✅ Watchdog réactivé
2. ✅ Récupération PID robuste
3. ✅ Fonction de nettoyage
4. ✅ Meilleur logging

**Résultat:** Jobs fantômes détectés et nettoyés automatiquement en 5-10 secondes max.

---

**Testé le:** 20 janvier 2026  
**Statut:** ✅ Correctifs appliqués et validés
