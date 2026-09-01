package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type fakeRunner struct{ called bool }

func (f *fakeRunner) RemoveAuthMAC(_ context.Context, _ string) error {
	f.called = true
	return nil
}

func TestTickRevokesExhaustedSession(t *testing.T) {
	r := &fakeRunner{}
	d := &daemon{sessions: map[string]*session{}, runner: r, quotaLocation: time.UTC, lastResetDay: time.Now().UTC().Format("2006-01-02")}
	d.sessions["s1"] = &session{SessionID: "s1", ClientMAC: "aa:bb", DailyMinute: 1, LastSeen: time.Now().Add(-2 * time.Minute), UsedSeconds: 0}
	d.tick()
	if _, ok := d.sessions["s1"]; ok {
		t.Fatal("expected session removed")
	}
	if !r.called {
		t.Fatal("expected runner called")
	}
}

func TestAllowProxyNoSession(t *testing.T) {
	d := &daemon{sessions: map[string]*session{}, quotaLocation: time.UTC, lastResetDay: time.Now().UTC().Format("2006-01-02")}
	req := httptest.NewRequest(http.MethodPost, "/v1/proxy/allow", strings.NewReader(`{"session_id":"missing","client_mac":"aa:bb:cc:dd:ee:ff"}`))
	rec := httptest.NewRecorder()
	d.allowProxy(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status %d", rec.Code)
	}
	var out map[string]bool
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if out["allowed"] {
		t.Fatal("expected allow=false")
	}
}

func TestTickResetsUsageOnNewDay(t *testing.T) {
	now := time.Now().UTC()
	d := &daemon{
		sessions:      map[string]*session{},
		runner:        &fakeRunner{},
		quotaLocation: time.UTC,
		lastResetDay:  now.AddDate(0, 0, -1).Format("2006-01-02"),
	}
	d.sessions["s1"] = &session{SessionID: "s1", ClientMAC: "aa:bb:cc:dd:ee:ff", DailyMinute: 5, LastSeen: now.Add(-time.Hour), UsedSeconds: 250}
	d.tick()
	if got := d.sessions["s1"].UsedSeconds; got != 0 {
		t.Fatalf("expected usage reset, got %d", got)
	}
}
