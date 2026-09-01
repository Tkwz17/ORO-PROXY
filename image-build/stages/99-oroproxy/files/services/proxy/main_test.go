package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestQuotaAllow(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req quotaRequest
		_ = json.NewDecoder(r.Body).Decode(&req)
		if req.SessionID == "s1" && req.ClientMAC == "aa:bb:cc:dd:ee:ff" {
			_ = json.NewEncoder(w).Encode(quotaResponse{Allowed: true})
			return
		}
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer ts.Close()

	qc := &quotaClient{baseURL: ts.URL, http: &http.Client{Timeout: time.Second}}
	ok, reachable := qc.allow(context.Background(), "s1", "AA:BB:CC:DD:EE:FF")
	if !ok || !reachable {
		t.Fatal("expected allow true")
	}
	if allowed, _ := qc.allow(context.Background(), "", "aa"); allowed {
		t.Fatal("expected denied for empty session")
	}
}

func TestCopyHeader(t *testing.T) {
	src := make(http.Header)
	src.Add("X-Test", "a")
	src.Add("X-Test", "b")
	dst := make(http.Header)
	copyHeader(dst, src)
	if got := bytes.Join([][]byte{[]byte(dst.Get("X-Test"))}, nil); len(got) == 0 {
		t.Fatal("expected copied headers")
	}
}

func TestGracefulDegradationAllowsRecentlyValidatedSession(t *testing.T) {
	srv := &proxyServer{
		quota:              &quotaClient{baseURL: "http://127.0.0.1:1", http: &http.Client{Timeout: 50 * time.Millisecond}},
		lastAllowedSession: map[string]time.Time{},
		gracePeriod:        time.Minute,
	}
	srv.markAllowed("s1", "aa:bb:cc:dd:ee:ff")
	if !srv.wasRecentlyAllowed("s1", "aa:bb:cc:dd:ee:ff") {
		t.Fatal("expected recent session allowed")
	}
}
