package filestore_util

import (
	"errors"
	"fmt"
	"io"
	"io/ioutil"

	k "github.com/ipfs/go-ipfs/blocks/key"
	cmds "github.com/ipfs/go-ipfs/commands"
	"github.com/ipfs/go-ipfs/core"
	. "github.com/ipfs/go-ipfs/filestore"
	b58 "gx/ipfs/QmT8rehPR3F6bmwL6zjUN8XpiDBFFpMP2myPdC6ApsWfJf/go-base58"
)

func Clean(req cmds.Request, node *core.IpfsNode, fs *Datastore, quiet bool, what ...string) (io.Reader, error) {
	stage1 := false
	stage2 := false
	stage3 := false
	to_remove := make([]bool, 100)
	for i := 0; i < len(what); i++ {
		switch what[i] {
		case "invalid":
			what = append(what, "changed", "no-file")
		case "full":
			what = append(what, "invalid", "incomplete", "orphan")
		case "changed":
			stage1 = true
			to_remove[StatusFileChanged] = true
		case "no-file":
			stage1 = true
			to_remove[StatusFileMissing] = true
		case "error":
			stage1 = true
			to_remove[StatusFileError] = true
		case "incomplete":
			stage2 = true
			to_remove[StatusIncomplete] = true
		case "orphan":
			stage3 = true
			to_remove[StatusOrphan] = true
		default:
			return nil, errors.New("invalid arg: " + what[i])
		}
	}
	rdr, wtr := io.Pipe()
	var rmWtr io.Writer = wtr
	if quiet {
		rmWtr = ioutil.Discard
	}
	do_stage := func(ch <-chan ListRes, err error) {
		if err != nil {
			wtr.CloseWithError(err)
			return
		}
		var toDel [][]byte
		for r := range ch {
			if to_remove[r.Status] {
				toDel = append(toDel, r.RawHash())
			}
		}
		for _, key := range toDel {
			err := Delete(req, rmWtr, node, fs, k.Key(key))
			if err != nil {
				mhash := b58.Encode(key)
				msg := fmt.Sprintf("Could not delete %s: %s\n", mhash, err.Error())
				wtr.CloseWithError(errors.New(msg))
				return
			}
		}
	}
	go func() {
		if stage1 {
			fmt.Fprintf(rmWtr, "Scanning for invalid leaf nodes ('verify --basic -l6') ...\n")
			do_stage(VerifyBasic(fs, 6, 1))
		}
		if stage2 {
			fmt.Fprintf(rmWtr, "Scanning for incomplete nodes ('verify -l1 --skip-orphans') ...\n")
		 	do_stage(VerifyFull(node, fs, 1, 1, true))
		}
		if stage3 {
			fmt.Fprintf(rmWtr, "Scanning for orphans ('verify -l1') ...\n")
		 	do_stage(VerifyFull(node, fs, 1, 1, false))
		}
		wtr.Close()
	}()
	return rdr, nil
}
