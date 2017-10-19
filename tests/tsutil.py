#
# Copyright (C) 2017 University of Oxford
#
# This file is part of msprime.
#
# msprime is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# msprime is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with msprime.  If not, see <http://www.gnu.org/licenses/>.
#
"""
A collection of utilities to edit and construct tree sequences.
"""
from __future__ import print_function
from __future__ import unicode_literals
from __future__ import division

import random

import msprime


def subsample_sites(ts, num_sites):
    """
    Returns a copy of the specified tree sequence with a random subsample of the
    specified number of sites.
    """
    t = ts.dump_tables()
    t.sites.reset()
    t.mutations.reset()
    sites_to_keep = set(random.sample(list(range(ts.num_sites)), num_sites))
    for site in ts.sites():
        if site.index in sites_to_keep:
            site_id = len(t.sites)
            t.sites.add_row(
                position=site.position, ancestral_state=site.ancestral_state)
            for mutation in site.mutations:
                t.mutations.add_row(
                    site=site_id, derived_state=mutation.derived_state,
                    node=mutation.node, parent=mutation.parent)
    return msprime.load_tables(**t.asdict())


def decapitate(ts, num_edges):
    """
    Returns a copy of the specified tree sequence in which the specified number of
    edges have been retained.
    """
    t = ts.dump_tables()
    t.edges.set_columns(
        left=t.edges.left[:num_edges], right=t.edges.right[:num_edges],
        parent=t.edges.parent[:num_edges], child=t.edges.child[:num_edges])
    return msprime.load_tables(
        nodes=t.nodes, edges=t.edges, sites=t.sites, mutations=t.mutations,
        sequence_length=ts.sequence_length)


def insert_branch_mutations(ts, mutations_per_branch=1):
    """
    Returns a copy of the specified tree sequence with a mutation on every branch
    in every tree.
    """
    sites = msprime.SiteTable()
    mutations = msprime.MutationTable()
    for tree in ts.trees():
        site = len(sites)
        sites.add_row(position=tree.interval[0], ancestral_state='0')
        for root in tree.roots:
            state = {root: 0}
            mutation = {root: -1}
            stack = [root]
            while len(stack) > 0:
                u = stack.pop()
                stack.extend(tree.children(u))
                v = tree.parent(u)
                if v != msprime.NULL_NODE:
                    state[u] = state[v]
                    parent = mutation[v]
                    for j in range(mutations_per_branch):
                        state[u] = (state[u] + 1) % 2
                        mutation[u] = len(mutations)
                        mutations.add_row(
                            site=site, node=u, derived_state=str(state[u]),
                            parent=parent)
                        parent = mutation[u]
    tables = ts.tables
    return msprime.load_tables(
        nodes=tables.nodes, edges=tables.edges, sites=sites, mutations=mutations)


def permute_nodes(ts, node_map):
    """
    Returns a copy of the specified tree sequence such that the nodes are
    permuted according to the specified map.
    """
    # Mapping from nodes in the new tree sequence back to nodes in the original
    reverse_map = [0 for _ in node_map]
    for j in range(ts.num_nodes):
        reverse_map[node_map[j]] = j
    old_nodes = list(ts.nodes())
    new_nodes = msprime.NodeTable()
    for j in range(ts.num_nodes):
        old_node = old_nodes[reverse_map[j]]
        new_nodes.add_row(
            flags=old_node.flags, name=old_node.name,
            population=old_node.population, time=old_node.time)
    new_edges = msprime.EdgeTable()
    for edge in ts.edges():
        new_edges.add_row(
            left=edge.left, right=edge.right, parent=node_map[edge.parent],
            child=node_map[edge.child])
    new_sites = msprime.SiteTable()
    new_mutations = msprime.MutationTable()
    for site in ts.sites():
        new_sites.add_row(
            position=site.position, ancestral_state=site.ancestral_state)
        for mutation in site.mutations:
            new_mutations.add_row(
                site=site.index, derived_state=mutation.derived_state,
                node=node_map[mutation.node])
    msprime.sort_tables(
        nodes=new_nodes, edges=new_edges, sites=new_sites, mutations=new_mutations)
    return msprime.load_tables(
        nodes=new_nodes, edges=new_edges, sites=new_sites, mutations=new_mutations)


def insert_redundant_breakpoints(ts):
    """
    Builds a new tree sequence containing redundant breakpoints.
    """
    tables = ts.dump_tables()
    tables.edges.reset()
    for r in ts.edges():
        x = r.left + (r.right - r.left) / 2
        tables.edges.add_row(
            left=r.left, right=x, child=r.child, parent=r.parent)
        tables.edges.add_row(
            left=x, right=r.right, child=r.child, parent=r.parent)
    new_ts = msprime.load_tables(**tables.asdict())
    assert new_ts.num_edges == 2 * ts.num_edges
    return new_ts


def single_childify(ts):
    """
    Builds a new equivalent tree sequence which contains an extra node in the
    middle of all exising branches.
    """
    tables = ts.dump_tables()
    edges = tables.edges
    nodes = tables.nodes
    sites = tables.sites
    mutations = tables.mutations

    time = nodes.time[:]
    edges.reset()
    for edge in ts.edges():
        # Insert a new node in between the parent and child.
        u = len(nodes)
        t = time[edge.child] + (time[edge.parent] - time[edge.child]) / 2
        nodes.add_row(time=t)
        edges.add_row(
            left=edge.left, right=edge.right, parent=u, child=edge.child)
        edges.add_row(
            left=edge.left, right=edge.right, parent=edge.parent, child=u)
    msprime.sort_tables(
        nodes=nodes, edges=edges, sites=sites, mutations=mutations)
    new_ts = msprime.load_tables(
        nodes=nodes, edges=edges, sites=sites, mutations=mutations)
    return new_ts


def jiggle_samples(ts):
    """
    Returns a copy of the specified tree sequence with the sample nodes switched
    around. The first n / 2 existing samples become non samples, and the last
    n / 2 node become samples.
    """
    tables = ts.dump_tables()
    nodes = tables.nodes
    flags = nodes.flags
    oldest_parent = tables.edges.parent[-1]
    n = ts.sample_size
    flags[:n // 2] = 0
    flags[oldest_parent - n // 2: oldest_parent] = 1
    nodes.set_columns(flags, nodes.time)
    return msprime.load_tables(nodes=nodes, edges=tables.edges)