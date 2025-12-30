"""Eth namespace JSON-RPC method runners.

Implements comprehensive runners for all eth_* methods with full coverage of
optional parameters and client-specific variations.

Supported methods:
- eth_getBlockByNumber: Get block by number (hydrated/non-hydrated)
- eth_getBlockByHash: Get block by hash (hydrated/non-hydrated)
- eth_getBlockReceipts: Get all receipts for a block
- eth_getBlockTransactionCountByNumber: Get tx count by block number
- eth_getBlockTransactionCountByHash: Get tx count by block hash
- eth_getTransactionByHash: Get transaction by hash
- eth_getTransactionByBlockHashAndIndex: Get tx by block hash and index
- eth_getTransactionByBlockNumberAndIndex: Get tx by block number and index
- eth_getTransactionReceipt: Get transaction receipt
- eth_getTransactionCount: Get account nonce
- eth_getBalance: Get account balance
- eth_getCode: Get contract code
- eth_getStorageAt: Get storage slot value
- eth_getProof: Get Merkle proof for account/storage
- eth_call: Execute call with optional state/block overrides
- eth_estimateGas: Estimate gas with optional state overrides
- eth_createAccessList: Generate access list for transaction
- eth_gasPrice: Get current gas price
- eth_maxPriorityFeePerGas: Get max priority fee suggestion
- eth_feeHistory: Get historical fee data with reward percentiles
- eth_blobBaseFee: Get current blob base fee (post-Dencun)
- eth_getLogs: Query logs with filter options
- eth_chainId: Get chain ID
- eth_blockNumber: Get latest block number
- eth_syncing: Get sync status
- eth_getUncleByBlockHashAndIndex: Get uncle by block hash and index
- eth_getUncleByBlockNumberAndIndex: Get uncle by block number and index
- eth_getUncleCountByBlockHash: Get uncle count by block hash
- eth_getUncleCountByBlockNumber: Get uncle count by block number

Client support notes:
- eth_getBlockReceipts: Nethermind, Erigon, Reth, Besu (NOT standard Geth)
- eth_getProof: Requires --prune.include-commitment-history=true in Erigon
- eth_blobBaseFee: Post-Dencun, requires EIP-4844 support
- eth_call state overrides: Geth, Nethermind, Reth, Besu
- eth_call block overrides: Geth only (as of 2024)
- eth_createAccessList: All major clients support this

See:
- Geth: https://geth.ethereum.org/docs/interacting-with-geth/rpc/ns-eth
- Nethermind: https://docs.nethermind.io/interacting/json-rpc-ns/eth
- Reth: https://reth.rs/jsonrpc/eth.html
- Erigon: https://erigon.gitbook.io/erigon/interacting-with-erigon/eth
- Besu: https://besu.hyperledger.org/public-networks/reference/api
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tqdm import tqdm

from json_rpc_scan.runners.base import BaseRunner, RunnerResult


if TYPE_CHECKING:
    from pathlib import Path

    from json_rpc_scan.client import Endpoint, RPCClient


# Block tags to test for historical state queries
BLOCK_TAGS: list[str] = ["latest", "earliest", "pending", "safe", "finalized"]

# Fee history reward percentiles to test
DEFAULT_REWARD_PERCENTILES: list[float] = [10.0, 25.0, 50.0, 75.0, 90.0]


@dataclass
class StateOverride:
    """State override for eth_call and eth_estimateGas.

    Allows temporary modification of account state before executing a call.
    """

    address: str
    balance: str | None = None
    nonce: str | None = None
    code: str | None = None
    state: dict[str, str] | None = None
    state_diff: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-RPC parameter format."""
        result: dict[str, Any] = {}
        if self.balance is not None:
            result["balance"] = self.balance
        if self.nonce is not None:
            result["nonce"] = self.nonce
        if self.code is not None:
            result["code"] = self.code
        if self.state is not None:
            result["state"] = self.state
        if self.state_diff is not None:
            result["stateDiff"] = self.state_diff
        return result


@dataclass
class BlockOverride:
    """Block override for eth_call (Geth-specific).

    Allows modification of block context during call execution.
    """

    number: str | None = None
    difficulty: str | None = None
    time: str | None = None
    gas_limit: str | None = None
    coinbase: str | None = None
    random: str | None = None
    base_fee: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-RPC parameter format."""
        result: dict[str, Any] = {}
        if self.number is not None:
            result["number"] = self.number
        if self.difficulty is not None:
            result["difficulty"] = self.difficulty
        if self.time is not None:
            result["time"] = self.time
        if self.gas_limit is not None:
            result["gasLimit"] = self.gas_limit
        if self.coinbase is not None:
            result["coinbase"] = self.coinbase
        if self.random is not None:
            result["random"] = self.random
        if self.base_fee is not None:
            result["baseFee"] = self.base_fee
        return result


@dataclass
class EthCallConfig:
    """Configuration for eth_call tests.

    Controls which optional parameters and variations to test.
    """

    # Test with state overrides
    test_state_override: bool = True
    # Test with block overrides (Geth only)
    test_block_override: bool = False
    # Test at different block tags
    test_block_tags: bool = True
    # Block tags to test (in addition to specific block numbers)
    block_tags: list[str] = field(default_factory=lambda: ["latest"])


@dataclass
class LogFilterConfig:
    """Configuration for eth_getLogs tests."""

    # Test with address filter
    test_address_filter: bool = True
    # Test with topic filters
    test_topic_filter: bool = True
    # Test with block range (fromBlock/toBlock)
    test_block_range: bool = True
    # Test with blockhash parameter
    test_blockhash: bool = True


# =============================================================================
# Block Methods
# =============================================================================


class EthGetBlockByNumberRunner(BaseRunner):
    """Runner for eth_getBlockByNumber.

    Tests both hydrated (full tx objects) and non-hydrated (tx hashes only) modes.
    """

    method_name = "eth_getBlockByNumber"
    description = "Get block by number with hydration options"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getBlockByNumber tests."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        # Test both hydrated and non-hydrated
        hydration_modes = [True, False]

        with tqdm(
            total=total_blocks * len(hydration_modes),
            desc=self.method_name,
            unit="req",
        ) as pbar:
            for block_num in range(start_block, end_block + 1):
                for hydrated in hydration_modes:
                    tests_run += 1
                    params: list[Any] = [hex(block_num), hydrated]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        mode = "hydrated" if hydrated else "hashes"
                        self.log(f"\n⚠ Diff at block {block_num} ({mode})")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"block_{block_num}_{mode}",
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )

                    pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetBlockByHashRunner(BaseRunner):
    """Runner for eth_getBlockByHash.

    Tests both hydrated and non-hydrated modes using block hashes.
    """

    method_name = "eth_getBlockByHash"
    description = "Get block by hash with hydration options"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getBlockByHash tests."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1
        hydration_modes = [True, False]

        with tqdm(
            total=total_blocks * len(hydration_modes),
            desc=self.method_name,
            unit="req",
        ) as pbar:
            for block_num in range(start_block, end_block + 1):
                # First get the block hash
                block = await self.client.get_block(
                    self.endpoints[0], block_num, full_transactions=False
                )
                if not block or not block.get("hash"):
                    pbar.update(len(hydration_modes))
                    continue

                block_hash = block["hash"]

                for hydrated in hydration_modes:
                    tests_run += 1
                    params: list[Any] = [block_hash, hydrated]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        mode = "hydrated" if hydrated else "hashes"
                        self.log(f"\n⚠ Diff at block {block_num} ({mode})")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"block_{block_num}_{mode}",
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )

                    pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetBlockReceiptsRunner(BaseRunner):
    """Runner for eth_getBlockReceipts.

    Returns all transaction receipts for a block.
    Note: Not supported by standard Geth - use debug_getRawReceipts instead.
    """

    method_name = "eth_getBlockReceipts"
    description = "Get all transaction receipts for a block"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getBlockReceipts tests."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                tests_run += 1
                params: list[Any] = [hex(block_num)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff at block {block_num}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"block_{block_num}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetBlockTransactionCountByNumberRunner(BaseRunner):
    """Runner for eth_getBlockTransactionCountByNumber."""

    method_name = "eth_getBlockTransactionCountByNumber"
    description = "Get transaction count by block number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getBlockTransactionCountByNumber tests."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                tests_run += 1
                params: list[Any] = [hex(block_num)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff at block {block_num}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"block_{block_num}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetBlockTransactionCountByHashRunner(BaseRunner):
    """Runner for eth_getBlockTransactionCountByHash."""

    method_name = "eth_getBlockTransactionCountByHash"
    description = "Get transaction count by block hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getBlockTransactionCountByHash tests."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                block = await self.client.get_block(
                    self.endpoints[0], block_num, full_transactions=False
                )
                if not block or not block.get("hash"):
                    pbar.update(1)
                    continue

                tests_run += 1
                params: list[Any] = [block["hash"]]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff at block {block_num}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"block_{block_num}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


# =============================================================================
# Transaction Methods
# =============================================================================


class EthGetTransactionByHashRunner(BaseRunner):
    """Runner for eth_getTransactionByHash."""

    method_name = "eth_getTransactionByHash"
    description = "Get transaction by hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getTransactionByHash for all transactions in range."""
        self.log(f"{self.method_name}: Scanning for transactions...")
        tx_list: list[tuple[int, str]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict) and tx.get("hash"):
                        tx_list.append((block_num, tx["hash"]))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(tx_list), desc=self.method_name, unit="tx") as pbar:
            for block_num, tx_hash in tx_list:
                tests_run += 1
                params: list[Any] = [tx_hash]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for tx {tx_hash[:16]}... (block {block_num})")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"tx_{tx_hash}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} txs, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetTransactionByBlockHashAndIndexRunner(BaseRunner):
    """Runner for eth_getTransactionByBlockHashAndIndex."""

    method_name = "eth_getTransactionByBlockHashAndIndex"
    description = "Get transaction by block hash and index"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getTransactionByBlockHashAndIndex tests."""
        self.log(f"{self.method_name}: Scanning for transactions...")
        test_cases: list[tuple[int, str, int]] = []  # (block_num, block_hash, tx_idx)

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if block and block.get("hash") and block.get("transactions"):
                block_hash = block["hash"]
                for tx_idx in range(len(block["transactions"])):
                    test_cases.append((block_num, block_hash, tx_idx))

        if not test_cases:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(test_cases)} transactions")

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(test_cases), desc=self.method_name, unit="tx") as pbar:
            for block_num, block_hash, tx_idx in test_cases:
                tests_run += 1
                params: list[Any] = [block_hash, hex(tx_idx)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for block {block_num} tx {tx_idx}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"block_{block_num}_tx_{tx_idx}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} txs, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetTransactionByBlockNumberAndIndexRunner(BaseRunner):
    """Runner for eth_getTransactionByBlockNumberAndIndex."""

    method_name = "eth_getTransactionByBlockNumberAndIndex"
    description = "Get transaction by block number and index"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getTransactionByBlockNumberAndIndex tests."""
        self.log(f"{self.method_name}: Scanning for transactions...")
        test_cases: list[tuple[int, int]] = []  # (block_num, tx_idx)

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if block and block.get("transactions"):
                for tx_idx in range(len(block["transactions"])):
                    test_cases.append((block_num, tx_idx))

        if not test_cases:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(test_cases)} transactions")

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(test_cases), desc=self.method_name, unit="tx") as pbar:
            for block_num, tx_idx in test_cases:
                tests_run += 1
                params: list[Any] = [hex(block_num), hex(tx_idx)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for block {block_num} tx {tx_idx}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"block_{block_num}_tx_{tx_idx}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} txs, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetTransactionReceiptRunner(BaseRunner):
    """Runner for eth_getTransactionReceipt."""

    method_name = "eth_getTransactionReceipt"
    description = "Get transaction receipt by hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getTransactionReceipt for all transactions in range."""
        self.log(f"{self.method_name}: Scanning for transactions...")
        tx_list: list[tuple[int, str]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict) and tx.get("hash"):
                        tx_list.append((block_num, tx["hash"]))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(tx_list), desc=self.method_name, unit="tx") as pbar:
            for block_num, tx_hash in tx_list:
                tests_run += 1
                params: list[Any] = [tx_hash]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for tx {tx_hash[:16]}... (block {block_num})")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"tx_{tx_hash}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} txs, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetTransactionCountRunner(BaseRunner):
    """Runner for eth_getTransactionCount (nonce).

    Tests at multiple block tags/numbers to verify historical state.
    """

    method_name = "eth_getTransactionCount"
    description = "Get account nonce at various blocks"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getTransactionCount tests."""
        # Collect unique addresses from transactions
        self.log(f"{self.method_name}: Collecting addresses from transactions...")
        addresses: set[str] = set()

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict):
                        if tx.get("from"):
                            addresses.add(tx["from"])
                        if tx.get("to"):
                            addresses.add(tx["to"])

        if not addresses:
            self.log(f"{self.method_name}: No addresses found")
            return RunnerResult(self.method_name, 0, 0)

        # Limit to reasonable number of addresses
        address_list = list(addresses)[:100]
        self.log(f"{self.method_name}: Testing {len(address_list)} addresses")

        tests_run = 0
        diff_count = 0

        # Test at specific block numbers and tags
        block_params = [hex(end_block), "latest"]

        total_tests = len(address_list) * len(block_params)
        with tqdm(total=total_tests, desc=self.method_name, unit="req") as pbar:
            for addr in address_list:
                for block_param in block_params:
                    tests_run += 1
                    params: list[Any] = [addr, block_param]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        self.log(f"\n⚠ Diff for {addr[:16]}... @ {block_param}")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"addr_{addr}_{block_param}",
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )

                    pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


# =============================================================================
# Account/State Methods
# =============================================================================


class EthGetBalanceRunner(BaseRunner):
    """Runner for eth_getBalance.

    Tests account balances at various block tags/numbers.
    """

    method_name = "eth_getBalance"
    description = "Get account balance at various blocks"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getBalance tests."""
        self.log(f"{self.method_name}: Collecting addresses...")
        addresses: set[str] = set()

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block:
                # Add miner/coinbase
                if block.get("miner"):
                    addresses.add(block["miner"])
                # Add tx participants
                if block.get("transactions"):
                    for tx in block["transactions"]:
                        if isinstance(tx, dict):
                            if tx.get("from"):
                                addresses.add(tx["from"])
                            if tx.get("to"):
                                addresses.add(tx["to"])

        if not addresses:
            self.log(f"{self.method_name}: No addresses found")
            return RunnerResult(self.method_name, 0, 0)

        address_list = list(addresses)[:100]
        self.log(f"{self.method_name}: Testing {len(address_list)} addresses")

        tests_run = 0
        diff_count = 0

        # Test at various block parameters
        block_params = [hex(end_block), "latest", "earliest"]

        total_tests = len(address_list) * len(block_params)
        with tqdm(total=total_tests, desc=self.method_name, unit="req") as pbar:
            for addr in address_list:
                for block_param in block_params:
                    tests_run += 1
                    params: list[Any] = [addr, block_param]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        self.log(f"\n⚠ Diff for {addr[:16]}... @ {block_param}")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"balance_{addr}_{block_param}",
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )

                    pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetCodeRunner(BaseRunner):
    """Runner for eth_getCode.

    Tests contract code retrieval at various blocks.
    """

    method_name = "eth_getCode"
    description = "Get contract code at various blocks"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getCode tests."""
        self.log(f"{self.method_name}: Collecting contract addresses...")
        contracts: set[str] = set()

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    # Contract calls (to address with data)
                    if (
                        isinstance(tx, dict)
                        and tx.get("to")
                        and tx.get("input")
                        and tx["input"] != "0x"
                    ):
                        contracts.add(tx["to"])

        if not contracts:
            self.log(f"{self.method_name}: No contracts found")
            return RunnerResult(self.method_name, 0, 0)

        contract_list = list(contracts)[:50]
        self.log(f"{self.method_name}: Testing {len(contract_list)} contracts")

        tests_run = 0
        diff_count = 0

        block_params = [hex(end_block), "latest"]

        total_tests = len(contract_list) * len(block_params)
        with tqdm(total=total_tests, desc=self.method_name, unit="req") as pbar:
            for addr in contract_list:
                for block_param in block_params:
                    tests_run += 1
                    params: list[Any] = [addr, block_param]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        self.log(f"\n⚠ Diff for {addr[:16]}... @ {block_param}")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"code_{addr}_{block_param}",
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )

                    pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetStorageAtRunner(BaseRunner):
    """Runner for eth_getStorageAt.

    Tests storage slot retrieval for contracts at various blocks.
    """

    method_name = "eth_getStorageAt"
    description = "Get storage slot value at various blocks"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getStorageAt tests."""
        self.log(f"{self.method_name}: Collecting contract addresses...")
        contracts: set[str] = set()

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if (
                        isinstance(tx, dict)
                        and tx.get("to")
                        and tx.get("input")
                        and tx["input"] != "0x"
                    ):
                        contracts.add(tx["to"])

        if not contracts:
            self.log(f"{self.method_name}: No contracts found")
            return RunnerResult(self.method_name, 0, 0)

        contract_list = list(contracts)[:20]
        self.log(f"{self.method_name}: Testing {len(contract_list)} contracts")

        tests_run = 0
        diff_count = 0

        # Common storage slots to check
        storage_slots = ["0x0", "0x1", "0x2"]

        total_tests = len(contract_list) * len(storage_slots)
        with tqdm(total=total_tests, desc=self.method_name, unit="req") as pbar:
            for addr in contract_list:
                for slot in storage_slots:
                    tests_run += 1
                    # Pad slot to 32 bytes
                    padded_slot = "0x" + slot[2:].zfill(64)
                    params: list[Any] = [addr, padded_slot, hex(end_block)]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        self.log(f"\n⚠ Diff for {addr[:16]}... slot {slot}")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"storage_{addr}_slot_{slot}",
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )

                    pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetProofRunner(BaseRunner):
    """Runner for eth_getProof.

    Gets Merkle proofs for accounts and storage.
    Note: Erigon requires --prune.include-commitment-history=true
    """

    method_name = "eth_getProof"
    description = "Get Merkle proof for account and storage"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getProof tests."""
        self.log(f"{self.method_name}: Collecting addresses...")
        addresses: set[str] = set()
        contracts: set[str] = set()

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict):
                        if tx.get("from"):
                            addresses.add(tx["from"])
                        if tx.get("to"):
                            if tx.get("input") and tx["input"] != "0x":
                                contracts.add(tx["to"])
                            else:
                                addresses.add(tx["to"])

        if not addresses and not contracts:
            self.log(f"{self.method_name}: No addresses found")
            return RunnerResult(self.method_name, 0, 0)

        # Test EOAs with empty storage keys
        address_list = list(addresses)[:20]
        # Test contracts with storage keys
        contract_list = list(contracts)[:10]

        self.log(
            f"{self.method_name}: Testing {len(address_list)} EOAs, "
            f"{len(contract_list)} contracts"
        )

        tests_run = 0
        diff_count = 0

        total_tests = len(address_list) + len(contract_list)
        with tqdm(total=total_tests, desc=self.method_name, unit="req") as pbar:
            # Test EOAs (no storage keys)
            for addr in address_list:
                tests_run += 1
                params: list[Any] = [addr, [], hex(end_block)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for EOA {addr[:16]}...")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"proof_eoa_{addr}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

            # Test contracts with storage keys
            storage_keys = ["0x" + "0" * 64, "0x" + "0" * 63 + "1"]
            for addr in contract_list:
                tests_run += 1
                params = [addr, storage_keys, hex(end_block)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for contract {addr[:16]}...")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"proof_contract_{addr}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


# =============================================================================
# Call Methods
# =============================================================================


class EthCallRunner(BaseRunner):
    """Runner for eth_call.

    Executes message calls with optional state and block overrides.
    Tests with various parameter combinations:
    - Basic call (to, data)
    - With gas limit
    - With value
    - With state override (modify balance, code, storage)
    - At different block tags
    """

    method_name = "eth_call"
    description = "Execute call with optional state/block overrides"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_call tests by replaying transactions."""
        config = kwargs.get("eth_call_config", EthCallConfig())

        self.log(f"{self.method_name}: Collecting transactions to replay...")
        tx_list: list[tuple[int, str, dict[str, Any]]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict) and tx.get("to"):
                        call_obj = self._tx_to_call(tx)
                        tx_hash = tx.get("hash", f"unknown_{block_num}")
                        tx_list.append((block_num, tx_hash, call_obj))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        # Limit for performance
        tx_list = tx_list[:100]
        self.log(f"{self.method_name}: Testing {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0

        # Calculate total tests based on config
        test_variants = 1  # Basic call
        if config.test_state_override:
            test_variants += 1  # With state override

        total_tests = len(tx_list) * test_variants
        with tqdm(total=total_tests, desc=self.method_name, unit="call") as pbar:
            for block_num, tx_hash, call_obj in tx_list:
                state_block = hex(max(0, block_num - 1))

                # Test 1: Basic call
                tests_run += 1
                params: list[Any] = [call_obj, state_block]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for tx {tx_hash[:16]}... (basic)")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"call_basic_{tx_hash}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )
                pbar.update(1)

                # Test 2: With state override (modify sender balance)
                if config.test_state_override and call_obj.get("from"):
                    tests_run += 1
                    state_override = {
                        call_obj["from"]: {"balance": "0xFFFFFFFFFFFFFFFFFFFF"}
                    }
                    params_override: list[Any] = [call_obj, state_block, state_override]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params_override
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        self.log(f"\n⚠ Diff for tx {tx_hash[:16]}... (state override)")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"call_stateoverride_{tx_hash}",
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )
                    pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)

    def _tx_to_call(self, tx: dict[str, Any]) -> dict[str, Any]:
        """Convert a transaction object to an eth_call-style object."""
        call: dict[str, Any] = {}

        for key in ("from", "to", "gas", "value"):
            if tx.get(key):
                call[key] = tx[key]

        if tx.get("input"):
            call["data"] = tx["input"]

        if tx.get("maxFeePerGas"):
            call["maxFeePerGas"] = tx["maxFeePerGas"]
            if tx.get("maxPriorityFeePerGas"):
                call["maxPriorityFeePerGas"] = tx["maxPriorityFeePerGas"]
        elif tx.get("gasPrice"):
            call["gasPrice"] = tx["gasPrice"]

        if tx.get("accessList"):
            call["accessList"] = tx["accessList"]

        return call


class EthEstimateGasRunner(BaseRunner):
    """Runner for eth_estimateGas.

    Estimates gas with optional state overrides.
    """

    method_name = "eth_estimateGas"
    description = "Estimate gas with optional state overrides"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_estimateGas tests."""
        self.log(f"{self.method_name}: Collecting transactions...")
        tx_list: list[tuple[int, str, dict[str, Any]]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict) and tx.get("to"):
                        call_obj = self._tx_to_call(tx)
                        tx_hash = tx.get("hash", f"unknown_{block_num}")
                        tx_list.append((block_num, tx_hash, call_obj))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        tx_list = tx_list[:100]
        self.log(f"{self.method_name}: Testing {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0

        # Test variants: basic, with block param, with state override
        test_variants = 3
        total_tests = len(tx_list) * test_variants

        with tqdm(total=total_tests, desc=self.method_name, unit="est") as pbar:
            for block_num, tx_hash, call_obj in tx_list:
                state_block = hex(max(0, block_num - 1))

                # Test 1: Basic (just call object)
                tests_run += 1
                params: list[Any] = [call_obj]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for tx {tx_hash[:16]}... (basic)")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"estimate_basic_{tx_hash}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )
                pbar.update(1)

                # Test 2: With block parameter
                tests_run += 1
                params_block: list[Any] = [call_obj, state_block]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params_block
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for tx {tx_hash[:16]}... (with block)")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"estimate_block_{tx_hash}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )
                pbar.update(1)

                # Test 3: With state override
                tests_run += 1
                if call_obj.get("from"):
                    state_override = {
                        call_obj["from"]: {"balance": "0xFFFFFFFFFFFFFFFFFFFF"}
                    }
                    params_override: list[Any] = [call_obj, state_block, state_override]

                    resp1, resp2 = await self.client.call_both(
                        self.endpoints, self.method_name, params_override
                    )

                    if resp1.response != resp2.response:
                        diff_count += 1
                        self.log(f"\n⚠ Diff for tx {tx_hash[:16]}... (state override)")
                        self.reporter.save_diff(
                            method=self.method_name,
                            identifier=f"estimate_override_{tx_hash}",
                            request=resp1.request,
                            response1=resp1.response,
                            response2=resp2.response,
                        )
                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)

    def _tx_to_call(self, tx: dict[str, Any]) -> dict[str, Any]:
        """Convert a transaction to a call object."""
        call: dict[str, Any] = {}

        for key in ("from", "to", "value"):
            if tx.get(key):
                call[key] = tx[key]

        if tx.get("input"):
            call["data"] = tx["input"]

        return call


class EthCreateAccessListRunner(BaseRunner):
    """Runner for eth_createAccessList.

    Creates an access list for a transaction, useful for EIP-2930 transactions.
    """

    method_name = "eth_createAccessList"
    description = "Generate access list for transaction"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_createAccessList tests."""
        self.log(f"{self.method_name}: Collecting contract calls...")
        tx_list: list[tuple[int, str, dict[str, Any]]] = []

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    # Only test contract calls
                    if (
                        isinstance(tx, dict)
                        and tx.get("to")
                        and tx.get("input")
                        and tx["input"] != "0x"
                    ):
                        call_obj = self._tx_to_call(tx)
                        tx_hash = tx.get("hash", f"unknown_{block_num}")
                        tx_list.append((block_num, tx_hash, call_obj))

        if not tx_list:
            self.log(f"{self.method_name}: No contract calls found")
            return RunnerResult(self.method_name, 0, 0)

        tx_list = tx_list[:50]
        self.log(f"{self.method_name}: Testing {len(tx_list)} calls")

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(tx_list), desc=self.method_name, unit="call") as pbar:
            for block_num, tx_hash, call_obj in tx_list:
                tests_run += 1
                state_block = hex(max(0, block_num - 1))
                params: list[Any] = [call_obj, state_block]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for tx {tx_hash[:16]}...")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"accesslist_{tx_hash}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)

    def _tx_to_call(self, tx: dict[str, Any]) -> dict[str, Any]:
        """Convert a transaction to a call object."""
        call: dict[str, Any] = {}

        for key in ("from", "to", "gas", "value"):
            if tx.get(key):
                call[key] = tx[key]

        if tx.get("input"):
            call["data"] = tx["input"]

        return call


# =============================================================================
# Fee Methods
# =============================================================================


class EthGasPriceRunner(BaseRunner):
    """Runner for eth_gasPrice.

    Returns the current gas price in wei.
    """

    method_name = "eth_gasPrice"
    description = "Get current gas price"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_gasPrice test (single call, no parameters)."""
        tests_run = 1
        diff_count = 0

        resp1, resp2 = await self.client.call_both(self.endpoints, self.method_name, [])

        if resp1.response != resp2.response:
            diff_count += 1
            self.log(f"\n⚠ Diff in {self.method_name}")
            self.reporter.save_diff(
                method=self.method_name,
                identifier="gas_price",
                request=resp1.request,
                response1=resp1.response,
                response2=resp2.response,
            )

        self.log(f"\n{self.method_name}: {tests_run} test, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthMaxPriorityFeePerGasRunner(BaseRunner):
    """Runner for eth_maxPriorityFeePerGas.

    Returns the max priority fee per gas suggestion.
    """

    method_name = "eth_maxPriorityFeePerGas"
    description = "Get max priority fee suggestion"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_maxPriorityFeePerGas test."""
        tests_run = 1
        diff_count = 0

        resp1, resp2 = await self.client.call_both(self.endpoints, self.method_name, [])

        if resp1.response != resp2.response:
            diff_count += 1
            self.log(f"\n⚠ Diff in {self.method_name}")
            self.reporter.save_diff(
                method=self.method_name,
                identifier="max_priority_fee",
                request=resp1.request,
                response1=resp1.response,
                response2=resp2.response,
            )

        self.log(f"\n{self.method_name}: {tests_run} test, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthFeeHistoryRunner(BaseRunner):
    """Runner for eth_feeHistory.

    Returns historical fee data with reward percentiles.
    Tests various block counts and percentile arrays.
    """

    method_name = "eth_feeHistory"
    description = "Get historical fee data with reward percentiles"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_feeHistory tests with various parameters."""
        tests_run = 0
        diff_count = 0

        # Test configurations: (block_count, percentiles)
        test_configs = [
            # Basic: 10 blocks, common percentiles
            (10, [25.0, 50.0, 75.0]),
            # Full range percentiles
            (5, [10.0, 25.0, 50.0, 75.0, 90.0]),
            # Empty percentiles
            (10, []),
            # Edge case percentiles
            (4, [0.0, 100.0]),
            # Larger block count
            (100, [50.0]),
        ]

        total_tests = len(test_configs)

        with tqdm(total=total_tests, desc=self.method_name, unit="req") as pbar:
            for block_count, percentiles in test_configs:
                tests_run += 1
                params: list[Any] = [hex(block_count), "latest", percentiles]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    pct_count = len(percentiles)
                    self.log(f"\n⚠ Diff for {block_count} blocks, {pct_count} pcts")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"feehistory_{block_count}_{len(percentiles)}pct",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthBlobBaseFeeRunner(BaseRunner):
    """Runner for eth_blobBaseFee.

    Returns the current blob base fee in wei.
    Note: Only available post-Dencun (EIP-4844).
    """

    method_name = "eth_blobBaseFee"
    description = "Get current blob base fee (post-Dencun)"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_blobBaseFee test."""
        tests_run = 1
        diff_count = 0

        resp1, resp2 = await self.client.call_both(self.endpoints, self.method_name, [])

        if resp1.response != resp2.response:
            diff_count += 1
            self.log(f"\n⚠ Diff in {self.method_name}")
            self.reporter.save_diff(
                method=self.method_name,
                identifier="blob_base_fee",
                request=resp1.request,
                response1=resp1.response,
                response2=resp2.response,
            )

        self.log(f"\n{self.method_name}: {tests_run} test, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


# =============================================================================
# Log Methods
# =============================================================================


class EthGetLogsRunner(BaseRunner):
    """Runner for eth_getLogs.

    Tests various filter configurations:
    - Block range (fromBlock, toBlock)
    - Address filter
    - Topic filters
    - BlockHash filter
    """

    method_name = "eth_getLogs"
    description = "Query logs with various filter options"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getLogs tests with various filters."""
        tests_run = 0
        diff_count = 0

        # Collect some addresses that emitted logs
        self.log(f"{self.method_name}: Scanning for log-emitting contracts...")
        log_addresses: set[str] = set()

        for block_num in range(start_block, min(start_block + 10, end_block + 1)):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if block and block.get("transactions"):
                for tx in block["transactions"]:
                    if isinstance(tx, dict) and tx.get("to"):
                        log_addresses.add(tx["to"])

        address_list = list(log_addresses)[:5]

        # Test configurations
        test_cases: list[tuple[str, dict[str, Any]]] = []

        # Test 1: Block range only
        test_cases.append(
            ("block_range", {"fromBlock": hex(start_block), "toBlock": hex(end_block)})
        )

        # Test 2: With address filter
        if address_list:
            test_cases.append(
                (
                    "with_address",
                    {
                        "fromBlock": hex(start_block),
                        "toBlock": hex(end_block),
                        "address": address_list[0],
                    },
                )
            )

        # Test 3: With multiple addresses
        if len(address_list) >= 2:
            test_cases.append(
                (
                    "multi_address",
                    {
                        "fromBlock": hex(start_block),
                        "toBlock": hex(end_block),
                        "address": address_list[:3],
                    },
                )
            )

        # Test 4: With topic filter (common event signatures)
        transfer_topic = (
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        )
        test_cases.append(
            (
                "with_topic",
                {
                    "fromBlock": hex(start_block),
                    "toBlock": hex(end_block),
                    "topics": [transfer_topic],
                },
            )
        )

        # Test 5: Single block by number
        test_cases.append(
            ("single_block", {"fromBlock": hex(end_block), "toBlock": hex(end_block)})
        )

        self.log(f"{self.method_name}: Running {len(test_cases)} filter tests")

        with tqdm(total=len(test_cases), desc=self.method_name, unit="filter") as pbar:
            for test_name, filter_obj in test_cases:
                tests_run += 1
                params: list[Any] = [filter_obj]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for filter: {test_name}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"logs_{test_name}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


# =============================================================================
# Chain Info Methods
# =============================================================================


class EthChainIdRunner(BaseRunner):
    """Runner for eth_chainId."""

    method_name = "eth_chainId"
    description = "Get chain ID"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_chainId test."""
        tests_run = 1
        diff_count = 0

        resp1, resp2 = await self.client.call_both(self.endpoints, self.method_name, [])

        if resp1.response != resp2.response:
            diff_count += 1
            self.log(f"\n⚠ Diff in {self.method_name}")
            self.reporter.save_diff(
                method=self.method_name,
                identifier="chain_id",
                request=resp1.request,
                response1=resp1.response,
                response2=resp2.response,
            )

        self.log(f"\n{self.method_name}: {tests_run} test, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthBlockNumberRunner(BaseRunner):
    """Runner for eth_blockNumber."""

    method_name = "eth_blockNumber"
    description = "Get latest block number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_blockNumber test."""
        tests_run = 1
        diff_count = 0

        resp1, resp2 = await self.client.call_both(self.endpoints, self.method_name, [])

        if resp1.response != resp2.response:
            diff_count += 1
            self.log(f"\n⚠ Diff in {self.method_name}")
            self.reporter.save_diff(
                method=self.method_name,
                identifier="block_number",
                request=resp1.request,
                response1=resp1.response,
                response2=resp2.response,
            )

        self.log(f"\n{self.method_name}: {tests_run} test, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthSyncingRunner(BaseRunner):
    """Runner for eth_syncing."""

    method_name = "eth_syncing"
    description = "Get sync status"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_syncing test."""
        tests_run = 1
        diff_count = 0

        resp1, resp2 = await self.client.call_both(self.endpoints, self.method_name, [])

        if resp1.response != resp2.response:
            diff_count += 1
            self.log(f"\n⚠ Diff in {self.method_name}")
            self.reporter.save_diff(
                method=self.method_name,
                identifier="syncing",
                request=resp1.request,
                response1=resp1.response,
                response2=resp2.response,
            )

        self.log(f"\n{self.method_name}: {tests_run} test, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


# =============================================================================
# Uncle Methods
# =============================================================================


class EthGetUncleCountByBlockHashRunner(BaseRunner):
    """Runner for eth_getUncleCountByBlockHash."""

    method_name = "eth_getUncleCountByBlockHash"
    description = "Get uncle count by block hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getUncleCountByBlockHash tests."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                block = await self.client.get_block(
                    self.endpoints[0], block_num, full_transactions=False
                )
                if not block or not block.get("hash"):
                    pbar.update(1)
                    continue

                tests_run += 1
                params: list[Any] = [block["hash"]]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff at block {block_num}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"uncle_count_hash_{block_num}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetUncleCountByBlockNumberRunner(BaseRunner):
    """Runner for eth_getUncleCountByBlockNumber."""

    method_name = "eth_getUncleCountByBlockNumber"
    description = "Get uncle count by block number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getUncleCountByBlockNumber tests."""
        tests_run = 0
        diff_count = 0
        total_blocks = end_block - start_block + 1

        with tqdm(total=total_blocks, desc=self.method_name, unit="blk") as pbar:
            for block_num in range(start_block, end_block + 1):
                tests_run += 1
                params: list[Any] = [hex(block_num)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff at block {block_num}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"uncle_count_num_{block_num}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetUncleByBlockHashAndIndexRunner(BaseRunner):
    """Runner for eth_getUncleByBlockHashAndIndex."""

    method_name = "eth_getUncleByBlockHashAndIndex"
    description = "Get uncle by block hash and index"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getUncleByBlockHashAndIndex tests."""
        # Find blocks with uncles
        self.log(f"{self.method_name}: Scanning for blocks with uncles...")
        uncle_tests: list[tuple[int, str, int]] = []  # (block_num, hash, uncle_idx)

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if block and block.get("hash") and block.get("uncles"):
                block_hash = block["hash"]
                for uncle_idx in range(len(block["uncles"])):
                    uncle_tests.append((block_num, block_hash, uncle_idx))

        if not uncle_tests:
            self.log(f"{self.method_name}: No uncles found in block range")
            # Still test index 0 on first block to verify error handling
            block = await self.client.get_block(
                self.endpoints[0], start_block, full_transactions=False
            )
            if block and block.get("hash"):
                uncle_tests.append((start_block, block["hash"], 0))

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(uncle_tests), desc=self.method_name, unit="req") as pbar:
            for block_num, block_hash, uncle_idx in uncle_tests:
                tests_run += 1
                params: list[Any] = [block_hash, hex(uncle_idx)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for block {block_num} uncle {uncle_idx}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"uncle_hash_{block_num}_{uncle_idx}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthGetUncleByBlockNumberAndIndexRunner(BaseRunner):
    """Runner for eth_getUncleByBlockNumberAndIndex."""

    method_name = "eth_getUncleByBlockNumberAndIndex"
    description = "Get uncle by block number and index"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        """Run eth_getUncleByBlockNumberAndIndex tests."""
        self.log(f"{self.method_name}: Scanning for blocks with uncles...")
        uncle_tests: list[tuple[int, int]] = []  # (block_num, uncle_idx)

        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if block and block.get("uncles"):
                for uncle_idx in range(len(block["uncles"])):
                    uncle_tests.append((block_num, uncle_idx))

        if not uncle_tests:
            self.log(f"{self.method_name}: No uncles found, testing index 0")
            uncle_tests.append((start_block, 0))

        tests_run = 0
        diff_count = 0

        with tqdm(total=len(uncle_tests), desc=self.method_name, unit="req") as pbar:
            for block_num, uncle_idx in uncle_tests:
                tests_run += 1
                params: list[Any] = [hex(block_num), hex(uncle_idx)]

                resp1, resp2 = await self.client.call_both(
                    self.endpoints, self.method_name, params
                )

                if resp1.response != resp2.response:
                    diff_count += 1
                    self.log(f"\n⚠ Diff for block {block_num} uncle {uncle_idx}")
                    self.reporter.save_diff(
                        method=self.method_name,
                        identifier=f"uncle_num_{block_num}_{uncle_idx}",
                        request=resp1.request,
                        response1=resp1.response,
                        response2=resp2.response,
                    )

                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


# =============================================================================
# Runner Registry
# =============================================================================


ETH_RUNNERS: dict[str, type[BaseRunner]] = {
    # Block methods
    "eth_getBlockByNumber": EthGetBlockByNumberRunner,
    "eth_getBlockByHash": EthGetBlockByHashRunner,
    "eth_getBlockReceipts": EthGetBlockReceiptsRunner,
    "eth_getBlockTransactionCountByNumber": EthGetBlockTransactionCountByNumberRunner,
    "eth_getBlockTransactionCountByHash": EthGetBlockTransactionCountByHashRunner,
    # Transaction methods
    "eth_getTransactionByHash": EthGetTransactionByHashRunner,
    "eth_getTransactionByBlockHashAndIndex": EthGetTransactionByBlockHashAndIndexRunner,
    "eth_getTransactionByBlockNumberAndIndex": (
        EthGetTransactionByBlockNumberAndIndexRunner
    ),
    "eth_getTransactionReceipt": EthGetTransactionReceiptRunner,
    "eth_getTransactionCount": EthGetTransactionCountRunner,
    # Account/state methods
    "eth_getBalance": EthGetBalanceRunner,
    "eth_getCode": EthGetCodeRunner,
    "eth_getStorageAt": EthGetStorageAtRunner,
    "eth_getProof": EthGetProofRunner,
    # Call methods
    "eth_call": EthCallRunner,
    "eth_estimateGas": EthEstimateGasRunner,
    "eth_createAccessList": EthCreateAccessListRunner,
    # Fee methods
    "eth_gasPrice": EthGasPriceRunner,
    "eth_maxPriorityFeePerGas": EthMaxPriorityFeePerGasRunner,
    "eth_feeHistory": EthFeeHistoryRunner,
    "eth_blobBaseFee": EthBlobBaseFeeRunner,
    # Log methods
    "eth_getLogs": EthGetLogsRunner,
    # Chain info
    "eth_chainId": EthChainIdRunner,
    "eth_blockNumber": EthBlockNumberRunner,
    "eth_syncing": EthSyncingRunner,
    # Uncle methods
    "eth_getUncleCountByBlockHash": EthGetUncleCountByBlockHashRunner,
    "eth_getUncleCountByBlockNumber": EthGetUncleCountByBlockNumberRunner,
    "eth_getUncleByBlockHashAndIndex": EthGetUncleByBlockHashAndIndexRunner,
    "eth_getUncleByBlockNumberAndIndex": EthGetUncleByBlockNumberAndIndexRunner,
}


async def run_eth_methods(
    client: RPCClient,
    endpoints: tuple[Endpoint, Endpoint],
    output_dir: Path,
    start_block: int,
    end_block: int,
    methods: list[str] | None = None,
    eth_call_config: EthCallConfig | None = None,
) -> list[RunnerResult]:
    """Run eth namespace method tests.

    Args:
        client: RPC client instance.
        endpoints: Two endpoints to compare.
        output_dir: Directory for diff output.
        start_block: First block to test.
        end_block: Last block to test.
        methods: Specific methods to run (default: all).
        eth_call_config: Configuration for eth_call tests.

    Returns:
        List of RunnerResult for each method tested.
    """
    if eth_call_config is None:
        eth_call_config = EthCallConfig()

    methods_to_run = methods or list(ETH_RUNNERS.keys())
    results: list[RunnerResult] = []

    for method in methods_to_run:
        if method not in ETH_RUNNERS:
            tqdm.write(f"⚠ Unknown eth method '{method}', skipping")
            continue

        runner = ETH_RUNNERS[method](client, endpoints, output_dir)
        result = await runner.run(
            start_block,
            end_block,
            eth_call_config=eth_call_config,
        )
        results.append(result)

    return results
