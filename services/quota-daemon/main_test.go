package main

import (
	"context"
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
	d := &daemon{sessions: map[string]*session{}, runner: r}
	d.sessions["s1"] = &session{SessionID: "s1", ClientMAC: "aa:bb", DailyMinute: 1, LastSeen: time.Now().Add(-2 * time.Minute), UsedSeconds: 0}
	d.tick()
	if _, ok := d.sessions["s1"]; ok {
		t.Fatal("expected session removed")
	}
	if !r.called {
		t.Fatal("expected runner called")
	}
}
