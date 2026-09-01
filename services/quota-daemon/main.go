package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

type session struct {
	SessionID   string    `json:"session_id"`
	Username    string    `json:"username"`
	ClientMAC   string    `json:"client_mac"`
	DailyMinute int       `json:"daily_minutes"`
	StartedAt   time.Time `json:"started_at"`
	LastSeen    time.Time `json:"last_seen"`
	UsedSeconds int       `json:"used_seconds"`
}

type daemon struct {
	mu            sync.Mutex
	sessions      map[string]*session
	runner        nftRunner
	quotaLocation *time.Location
	lastResetDay  string
}

type nftRunner interface {
	RemoveAuthMAC(ctx context.Context, mac string) error
}

type shellRunner struct{}

func (shellRunner) RemoveAuthMAC(ctx context.Context, mac string) error {
	cmd := exec.CommandContext(ctx, "nft", "delete", "element", "inet", "oroproxy", "authenticated_macs", "{ "+mac+" }")
	return cmd.Run()
}

func main() {
	loc := loadLocation(getenv("OROPROXY_TIMEZONE", "Local"))
	now := time.Now().In(loc)
	d := &daemon{
		sessions:      map[string]*session{},
		runner:        shellRunner{},
		quotaLocation: loc,
		lastResetDay:  now.Format("2006-01-02"),
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/sessions/start", d.startSession)
	mux.HandleFunc("/v1/sessions/stop", d.stopSession)
	mux.HandleFunc("/v1/sessions/active", d.listSessions)
	mux.HandleFunc("/v1/proxy/allow", d.allowProxy)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })

	go d.enforceLoop()
	addr := getenv("OROPROXY_QUOTA_ADDR", ":9090")
	log.Printf("quota-daemon listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}

func (d *daemon) enforceLoop() {
	t := time.NewTicker(30 * time.Second)
	for range t.C {
		d.tick()
	}
}

func (d *daemon) tick() {
	now := time.Now()
	day := now.In(d.quotaLocation).Format("2006-01-02")
	d.mu.Lock()
	defer d.mu.Unlock()
	if day != d.lastResetDay {
		for _, s := range d.sessions {
			s.UsedSeconds = 0
			s.LastSeen = now
		}
		d.lastResetDay = day
		return
	}
	for sid, s := range d.sessions {
		delta := int(now.Sub(s.LastSeen).Seconds())
		if delta > 0 {
			s.UsedSeconds += delta
			s.LastSeen = now
		}
		if s.UsedSeconds >= s.DailyMinute*60 {
			_ = d.runner.RemoveAuthMAC(context.Background(), s.ClientMAC)
			delete(d.sessions, sid)
		}
	}
}

func (d *daemon) startSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var req session
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid payload", http.StatusBadRequest)
		return
	}
	if req.SessionID == "" || req.ClientMAC == "" || req.DailyMinute <= 0 {
		http.Error(w, "missing required fields", http.StatusBadRequest)
		return
	}
	now := time.Now()
	req.StartedAt = now
	req.LastSeen = now
	req.ClientMAC = strings.ToLower(req.ClientMAC)
	d.mu.Lock()
	d.sessions[req.SessionID] = &req
	d.mu.Unlock()
	w.WriteHeader(http.StatusCreated)
}

func (d *daemon) stopSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		SessionID string `json:"session_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.SessionID == "" {
		http.Error(w, "invalid payload", http.StatusBadRequest)
		return
	}
	d.mu.Lock()
	delete(d.sessions, req.SessionID)
	d.mu.Unlock()
	w.WriteHeader(http.StatusNoContent)
}

func (d *daemon) allowProxy(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		SessionID string `json:"session_id"`
		ClientMAC string `json:"client_mac"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid payload", http.StatusBadRequest)
		return
	}
	d.mu.Lock()
	s, ok := d.sessions[req.SessionID]
	allowed := ok && strings.EqualFold(s.ClientMAC, req.ClientMAC)
	if allowed {
		s.LastSeen = time.Now()
	}
	d.mu.Unlock()
	_ = json.NewEncoder(w).Encode(map[string]bool{"allowed": allowed})
}

func (d *daemon) listSessions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	out := make([]*session, 0, len(d.sessions))
	for _, s := range d.sessions {
		copy := *s
		out = append(out, &copy)
	}
	_ = json.NewEncoder(w).Encode(out)
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func loadLocation(name string) *time.Location {
	loc, err := time.LoadLocation(name)
	if err != nil {
		return time.Local
	}
	return loc
}
