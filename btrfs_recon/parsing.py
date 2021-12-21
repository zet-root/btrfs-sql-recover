import io
import typing
import uuid
from collections import deque
from typing import BinaryIO, Callable, Iterable

import construct as cs
from tqdm import tqdm

from btrfs_recon.structure import Header, Item, KeyType, ObjectId, Superblock, TreeNode
from btrfs_recon.types import DevId, PhysicalAddress
from btrfs_recon.util.chunk_cache import ChunkTreeCache


def parse_fs(*device_handles: BinaryIO) -> tuple[Superblock, ChunkTreeCache]:
    if not device_handles:
        raise ValueError('Please pass at least one device/image file handle')

    devid_fp_map = {}
    for fp in device_handles:
        superblock = cs.Pointer(0x10000, Superblock).parse_stream(fp)
        dev_item = superblock.dev_item
        devid_fp_map[dev_item.devid] = fp

    tree = ChunkTreeCache()
    for sys_chunk in superblock.sys_chunks:
        tree.insert(
            sys_chunk.key.offset,
            sys_chunk.chunk.length,
            sys_chunk.chunk.stripes,
        )

    chunk_tree_queue: deque[tuple[DevId, PhysicalAddress]] = deque(tree.offsets(superblock.chunk_root).items())
    while chunk_tree_queue:
        devid, physical = chunk_tree_queue.popleft()
        fp = devid_fp_map[devid]
        node = cs.Pointer(physical, TreeNode).parse_stream(fp)

        # print(f'=== CHUNK TREE ITEM: {hex(physical)} ({physical})')
        # print(chunk_tree_item)
        # print(f'===')
        # print()

        # Leaf node
        if node.header.level == 0:
            for item in node['items']:
                if item.key.ty != KeyType.ChunkItem:
                    continue

                tree.insert(
                    item.key.offset,
                    item.data.length,
                    item.data.stripes,
                )

                # print(f'=== CHUNK: {hex(chunk_physical)} ({chunk_physical})')
                # print(chunk)
                # print(f'===')
                # print()

        # Internal node (level != 0)
        else:
            for ptr in node['items']:
                node_physical = tree.offset(ptr.blockptr)
                chunk_tree_queue.append(node_physical)

    # root_tree_root_physical = tree.offset(superblock.root)
    # root_tree_queue = deque((root_tree_root_physical,))
    # while root_tree_queue:
    #     physical = root_tree_queue.popleft()
    #     root_tree_item = cs.Pointer(physical, Header).parse_stream(fs)
    #     print(physical)
    #     print(root_tree_item)

    return superblock, tree


def parse_at(fp, pos, type_, **contextkw):
    return cs.Pointer(pos, type_).parse_stream(fp, **contextkw)


def pparse_at(fp, pos, type_, **contextkw):
    print(parse_at(fp, pos, type_, **contextkw))


def walk_fs_tree(root: TreeNode):
    print(root)


class FindNodesLogFunc(typing.Protocol):
    def __call__(
        self,
        *values: object,
        sep: str | None = ...,
        end: str | None = ...,
        file: typing.TextIO | None = ...,
        flush: bool = ...,
    ) -> None: ...


def find_nodes(
    fp: io.FileIO, *,
    alignment: int = 0x10000,
    start_loc: int | None = None,
    reversed: bool = True,
    fsid: str | int | bytes | uuid.UUID | None = uuid.UUID('bba692f7-5be7-4173-bc27-bb3e21644739'),
    predicate: Callable[[int, Header], bool] | None = None,
    echo: bool = True,
    show_progress: bool = True,
) -> tuple[FindNodesLogFunc, Iterable[tuple[int, Header]]]:
    if fsid is not None and not isinstance(fsid, uuid.UUID):
        fsid = uuid.UUID(fsid)

    fp.seek(0, io.SEEK_END)
    file_size = fp.tell()
    max_loc = file_size - Header.sizeof()
    aligned_max_loc = max_loc - (max_loc % alignment)

    max_hex_length = len(f'0x{file_size:x}')
    max_int_length = len(f'{file_size}')

    if reversed:
        start_loc = aligned_max_loc if start_loc is None else start_loc
        loc_iter = range(start_loc, -1, -alignment)
    else:
        start_loc = 0 if start_loc is None else start_loc
        loc_iter = range(start_loc, aligned_max_loc + 1, alignment)

    if show_progress:
        pbar = tqdm(loc_iter, unit='loc')
        buf = io.StringIO()

        def log(*args, **kwargs):
            end = kwargs.pop('end', '\n')
            sep = kwargs.pop('sep', ' ')
            print(*args, end=end, sep=sep, file=buf)
            pbar.write(buf.getvalue(), end='', **kwargs)
            buf.seek(0)
            buf.truncate()
    else:
        pbar = loc_iter
        log = print

    def find_results() -> Iterable[tuple[int, Header]]:
        for loc in pbar:
            header = parse_at(fp, loc, Header)
            if fsid is not None and header.fsid != fsid:
                continue

            if predicate is not None and not predicate(loc, header):
                continue

            if echo:
                log(f'0x{loc:0{max_hex_length}x} ({loc:>{max_int_length}d})')

            yield loc, header

    return log, find_results()


def find_fs_roots(fp: io.FileIO, **kwargs) -> Iterable[tuple[int, Item]]:
    log, results = find_nodes(
        fp, **kwargs, predicate=lambda loc, header: header.level == 0 and header.nritems > 0
    )

    for loc, header in results:
        node = parse_at(fp, loc, TreeNode)
        for item in reversed(node['items']):
            if not (
                item.key.objectid == ObjectId.FsTree
                and item.key.ty == KeyType.RootItem
            ):
                continue

            log(f'\n\n!!!!!!!! FOUND ROOT TREE ITEM !!!!!!!!!!!!!')
            log(f'### Header — {hex(loc)} (loc)')
            log(str(header))
            log(f'\n')
            log(f'### Item')
            log(str(item))
            log('')
            log('')

            yield loc, item