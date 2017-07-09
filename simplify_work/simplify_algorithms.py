"""
Python versions of the algorithms from the paper.
"""
from __future__ import print_function
from __future__ import division

import sys
import random
import tempfile
import argparse
import heapq
import math

import msprime
import numpy as np

from six.moves import StringIO

from algorithms import *

class SearchablePopulation(Population):
    '''
    Like Population, but allows searching ancestors by index.
    '''
    def from_index(self, index):
        # obviously should do this differently
        for x in self._ancestors:
            if x.index ==index:
                return x
        return None

class Simplifier(Simulator):
    """
    Modified from Simulator().
    """
    def __init__(self, ts, samples, max_segments=100):
        # since we will have no migration events,
        # need to use one population but copy over population information
        N = 1
        sample_size = len(ts.samples())
        num_loci = ts.sequence_length

        self.ts = ts
        self.n = sample_size
        self.m = num_loci
        # self.r = recombination_rate
        # self.migration_matrix = migration_matrix
        self.max_segments = max_segments
        self.segment_stack = []
        self.segments = [None for j in range(self.max_segments + 1)]
        for j in range(self.max_segments):
            s = Segment(j + 1)
            self.segments[j + 1] = s
            self.segment_stack.append(s)
        self.P = [SearchablePopulation(id_) for id_ in range(N)]
        self.C = []
        self.L = FenwickTree(self.max_segments)
        self.S = bintrees.AVLTree()
        # records from `ts` refer to IDs that we must associate with ancestors
        # this mapping is recorded here:
        self.A = {}
        # set this as a constant to make code clear below
        self.pop_index = 0
        for k in range(sample_size):
            if k in samples:
                x = self.alloc_segment(0, self.m, k, self.pop_index)
                self.L.set_value(x.index, self.m - 1)
                self.P[self.pop_index].add(x)
                self.A[k] = x.index
        self.S[0] = self.n
        self.S[self.m] = -1
        self.t = 0
        self.w = self.n
        self.num_ca_events = 0
        self.num_re_events = 0

    def simplify(self):
        for edge in self.ts.edgesets():
            parent_node = self.ts.node(edge.parent)
            self.t = parent_node.time
            # pull out the ancestry segments that will be merged
            H = self.remove_ancestry(edge)
            # and merge them: just like merge_ancestors but needs to update A also
            self.merge_labeled_ancestors(H, edge.parent, self.pop_index)

    def get_ancestor(self, u):
        if u in self.A:
            out = self.P[self.pop_index].from_index(self.A[u])
        else:
            out = None
        return out

    def remove_ancestry(self, edge):
        """
        Remove (modifying in place) and return the subset of the ancestors 
        lying within the interval (left, right) for each of the children.
        Modified from paint_simplify::remove_paint().
        """
        H = []
        if edge.parent in self.A:
            w = self.get_ancestor(edge.parent)
            heapq.heappush(H, (w.left, w))
        for child in edge.children:
            if child in self.A:
                x = self.get_ancestor(child)
                # y will be the last segment to the left of edge, if any,
                #   which we may need to make sure links to the next one after
                y = None
                # and z will be the first segment after edge, if any
                z = None
                # and w will be the segment being sent to output
                w = None
                # flag for whether we're at the first segment of the ancestor
                # we are outputting to H
                output_head = True
                while x is not None and edge.right > x.left:
                    if edge.left <= x.right and edge.right >= x.left:
                        # we have overlap
                        seg_right = x.right
                        out_left = max(edge.left, x.left)
                        out_right = min(edge.right, x.right)
                        overhang_left = (x.left < out_left)
                        overhang_right = (x.right > out_right)
                        if overhang_left:
                            # this means x will be the first before removed segment
                            y = x
                            # revise x to be the left part
                            x.right = out_left
                            # this segment will be sent to output
                            w = self.alloc_segment(
                                out_left, out_right, x.node, x.population, w, None)
                        else:
                            # remove x
                            x.prev = w
                            w = x
                            w.right = out_right
                        if output_head:
                            heapq.heappush(H, (w.left, w))
                            output_head = False
                        if overhang_right:
                            # add new segment for right overhang, which will be the last
                            z = self.alloc_segment(
                                out_right, seg_right, x.node, x.population, y, x.next)
                            if y is not None:
                                y.next = z
                            if x.next is not None:
                                x.next.prev = z
                            break
                    else:
                        # maybe THIS segment was the first one before edge
                        y = x
                    # move on to the next segment
                    x = x.next
                # don't do wrap-up if we haven't actually done anything
                if not output_head:
                    if not overhang_right:
                        z = x
                    if y is not None:
                        y.next = z
                    if z is not None:
                        z.prev = y
                    if y is None:
                        # must update A[child]
                        if z is None:
                            del self.A[child]
                        else:
                            self.A[child] = z.index
        return H

    def merge_labeled_ancestors(self, H, parent, pop_id):
        # H is a heapq of (x.left, x) tuples,
        # with x an ancestor, i.e., a list of segments.
        # This will merge everyone in H and add them to population pop_id
        pop = self.P[pop_id]
        defrag_required = False
        coalescence = False
        alpha = None
        z = None
        while len(H) > 0:
            # print("LOOP HEAD")
            # self.print_heaps(H)
            alpha = None
            l = H[0][0]
            X = []
            r_max = self.m + 1
            while len(H) > 0 and H[0][0] == l:
                x = heapq.heappop(H)[1]
                X.append(x)
                r_max = min(r_max, x.right)
            if len(H) > 0:
                r_max = min(r_max, H[0][0])
            if len(X) == 1:
                x = X[0]
                if len(H) > 0 and H[0][0] < x.right:
                    alpha = self.alloc_segment(
                        x.left, H[0][0], x.node, x.population)
                    x.left = H[0][0]
                    heapq.heappush(H, (x.left, x))
                else:
                    if x.next is not None:
                        y = x.next
                        heapq.heappush(H, (y.left, y))
                    alpha = x
                    alpha.next = None
            else:
                if not coalescence:
                    coalescence = True
                    self.w += 1
                u = self.w - 1
                # We must also break if the next left value is less than
                # any of the right values in the current overlap set.
                if l not in self.S:
                    j = self.S.floor_key(l)
                    self.S[l] = self.S[j]
                if r_max not in self.S:
                    j = self.S.floor_key(r_max)
                    self.S[r_max] = self.S[j]
                # Update the number of extant segments.
                if self.S[l] == len(X):
                    self.S[l] = 0
                    r = self.S.succ_key(l)
                else:
                    r = l
                    while r < r_max and self.S[r] != len(X):
                        self.S[r] -= len(X) - 1
                        r = self.S.succ_key(r)
                    alpha = self.alloc_segment(l, r, u, pop_id)
                # Update the heaps and make the record.
                children = []
                for x in X:
                    children.append(x.node)
                    if x.right == r:
                        self.free_segment(x)
                        if x.next is not None:
                            y = x.next
                            heapq.heappush(H, (y.left, y))
                    elif x.right > r:
                        x.left = r
                        heapq.heappush(H, (x.left, x))
                self.C.append((l, r, u, children, self.t))

            # loop tail; update alpha and integrate it into the state.
            if alpha is not None:
                if z is None:
                    pop.add(alpha)
                    self.A[parent] = alpha.index
                    self.L.set_value(alpha.index, alpha.right - alpha.left - 1)
                else:
                    defrag_required |= (
                        z.right == alpha.left and z.node == alpha.node)
                    z.next = alpha
                    self.L.set_value(alpha.index, alpha.right - z.right)
                alpha.prev = z
                z = alpha
        if defrag_required:
            self.defrag_segment_chain(z)
        if coalescence:
            self.defrag_breakpoints()


def run_simplify(args):
    """
    Runs simplify on the tree sequence.
    """
    ts = msprime.load(args.tree_sequence)
    samples = random.sample(ts.samples(), args.sample_size)
    random.seed(args.random_seed)
    s = Simplifier(ts, samples)
    s.simplify()
    nodes_file = StringIO()
    edgesets_file = StringIO()
    s.write_text(nodes_file, edgesets_file)
    nodes_file.seek(0)
    edgesets_file.seek(0)
    new_ts = msprime.load_text(nodes_file, edgesets_file)
    for t in new_ts.trees():
        print(t)
    # process_trees(new_ts)


def add_simplifier_arguments(parser):
    parser.add_argument("tree_sequence", type=str)
    parser.add_argument("sample_size", type=int)
    parser.add_argument(
        "--random_seed", "-s", type=int, default=1)


def main():
    parser = argparse.ArgumentParser()
    # This is required to get uniform behaviour in Python2 and Python3
    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.required = True

    simplify_parser = subparsers.add_parser(
        "simplify",
        help="Simplify the tree sequence to fewer samples..")
    add_simplifier_arguments(simplify_parser)
    simplify_parser.set_defaults(runner=run_simplify)

    args = parser.parse_args()
    args.runner(args)


if __name__ == "__main__":
    main()
