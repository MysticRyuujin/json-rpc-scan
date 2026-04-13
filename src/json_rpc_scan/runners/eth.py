"""Eth namespace JSON-RPC method runners.

Runners for all eth_* methods with full coverage of optional parameters and
client-specific variations. Simple-iterator runners use `BaseRunner.compare_over`;
multi-variant runners (eth_call, eth_estimateGas) loop manually over variants,
calling `self.compare_one` per variant.

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
from typing import TYPE_CHECKING, Any, ClassVar

from tqdm import tqdm

from json_rpc_scan.normalize import Normalizer, null_as_empty_bytes, sort_logs_by_index
from json_rpc_scan.runners.base import BaseRunner, RunnerResult, tx_to_call_obj


if TYPE_CHECKING:
    from pathlib import Path

    from json_rpc_scan.client import Endpoint, RPCClient


# Block tags to test for historical state queries
BLOCK_TAGS: list[str] = ["latest", "earliest", "pending", "safe", "finalized"]

# Fee history reward percentiles to test
DEFAULT_REWARD_PERCENTILES: list[float] = [10.0, 25.0, 50.0, 75.0, 90.0]


@dataclass
class StateOverride:
    """State override for eth_call and eth_estimateGas."""

    address: str
    balance: str | None = None
    nonce: str | None = None
    code: str | None = None
    state: dict[str, str] | None = None
    state_diff: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
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
    """Block override for eth_call (Geth-specific)."""

    number: str | None = None
    difficulty: str | None = None
    time: str | None = None
    gas_limit: str | None = None
    coinbase: str | None = None
    random: str | None = None
    base_fee: str | None = None

    def to_dict(self) -> dict[str, Any]:
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
    """Configuration for eth_call tests."""

    test_state_override: bool = True
    test_block_override: bool = False
    test_block_tags: bool = True
    block_tags: list[str] = field(default_factory=lambda: ["latest"])


@dataclass
class LogFilterConfig:
    """Configuration for eth_getLogs tests."""

    test_address_filter: bool = True
    test_topic_filter: bool = True
    test_block_range: bool = True
    test_blockhash: bool = True


# =============================================================================
# Block methods
# =============================================================================


class EthGetBlockByNumberRunner(BaseRunner):
    """Get block by number with hydration options.

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
        inputs: list[tuple[str, list[Any]]] = []
        for n in range(start_block, end_block + 1):
            for hydrated in (True, False):
                mode = "hydrated" if hydrated else "hashes"
                inputs.append((f"block_{n}_{mode}", [hex(n), hydrated]))
        return await self.compare_over(inputs, total=len(inputs), unit="req")


class EthGetBlockByHashRunner(BaseRunner):
    """Get block by hash with hydration options."""

    method_name = "eth_getBlockByHash"
    description = "Get block by hash with hydration options"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if not block or not block.get("hash"):
                continue
            for hydrated in (True, False):
                mode = "hydrated" if hydrated else "hashes"
                inputs.append((f"block_{block_num}_{mode}", [block["hash"], hydrated]))
        return await self.compare_over(inputs, total=len(inputs), unit="req")


class EthGetBlockReceiptsRunner(BaseRunner):
    """Get all transaction receipts for a block.

    Not supported by standard Geth — use debug_getRawReceipts there instead.
    """

    method_name = "eth_getBlockReceipts"
    description = "Get all transaction receipts for a block"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs = [(f"block_{n}", [hex(n)]) for n in range(start_block, end_block + 1)]
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


class EthGetBlockTransactionCountByNumberRunner(BaseRunner):
    """Get transaction count by block number."""

    method_name = "eth_getBlockTransactionCountByNumber"
    description = "Get transaction count by block number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs = [(f"block_{n}", [hex(n)]) for n in range(start_block, end_block + 1)]
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


class EthGetBlockTransactionCountByHashRunner(BaseRunner):
    """Get transaction count by block hash."""

    method_name = "eth_getBlockTransactionCountByHash"
    description = "Get transaction count by block hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if block and block.get("hash"):
                inputs.append((f"block_{block_num}", [block["hash"]]))
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


# =============================================================================
# Transaction methods
# =============================================================================


class EthGetTransactionByHashRunner(BaseRunner):
    """Get transaction by hash."""

    method_name = "eth_getTransactionByHash"
    description = "Get transaction by hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Scanning for transactions...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            for tx in block["transactions"]:
                if isinstance(tx, dict) and tx.get("hash"):
                    inputs.append((f"tx_{tx['hash']}", [tx["hash"]]))

        if not inputs:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(inputs)} transactions")
        return await self.compare_over(inputs, total=len(inputs), unit="tx")


class EthGetTransactionByBlockHashAndIndexRunner(BaseRunner):
    """Get transaction by block hash and index."""

    method_name = "eth_getTransactionByBlockHashAndIndex"
    description = "Get transaction by block hash and index"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Scanning for transactions...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if not block or not block.get("hash") or not block.get("transactions"):
                continue
            for tx_idx in range(len(block["transactions"])):
                inputs.append(
                    (
                        f"block_{block_num}_tx_{tx_idx}",
                        [block["hash"], hex(tx_idx)],
                    )
                )

        if not inputs:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(inputs)} transactions")
        return await self.compare_over(inputs, total=len(inputs), unit="tx")


class EthGetTransactionByBlockNumberAndIndexRunner(BaseRunner):
    """Get transaction by block number and index."""

    method_name = "eth_getTransactionByBlockNumberAndIndex"
    description = "Get transaction by block number and index"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Scanning for transactions...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if not block or not block.get("transactions"):
                continue
            for tx_idx in range(len(block["transactions"])):
                inputs.append(
                    (
                        f"block_{block_num}_tx_{tx_idx}",
                        [hex(block_num), hex(tx_idx)],
                    )
                )

        if not inputs:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(inputs)} transactions")
        return await self.compare_over(inputs, total=len(inputs), unit="tx")


class EthGetTransactionReceiptRunner(BaseRunner):
    """Get transaction receipt by hash."""

    method_name = "eth_getTransactionReceipt"
    description = "Get transaction receipt by hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Scanning for transactions...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            for tx in block["transactions"]:
                if isinstance(tx, dict) and tx.get("hash"):
                    inputs.append((f"tx_{tx['hash']}", [tx["hash"]]))

        if not inputs:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        self.log(f"{self.method_name}: Found {len(inputs)} transactions")
        return await self.compare_over(inputs, total=len(inputs), unit="tx")


class EthGetTransactionCountRunner(BaseRunner):
    """Get account nonce at various blocks."""

    method_name = "eth_getTransactionCount"
    description = "Get account nonce at various blocks"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Collecting addresses from transactions...")
        addresses: set[str] = set()
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
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

        block_params = [hex(end_block), "latest"]
        inputs: list[tuple[str, list[Any]]] = [
            (f"addr_{addr}_{block_param}", [addr, block_param])
            for addr in address_list
            for block_param in block_params
        ]
        return await self.compare_over(inputs, total=len(inputs), unit="req")


# =============================================================================
# Account / state methods
# =============================================================================


class EthGetBalanceRunner(BaseRunner):
    """Get account balance at various blocks."""

    method_name = "eth_getBalance"
    description = "Get account balance at various blocks"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Collecting addresses...")
        addresses: set[str] = set()
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block:
                continue
            if block.get("miner"):
                addresses.add(block["miner"])
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

        block_params = [hex(end_block), "latest", "earliest"]
        inputs: list[tuple[str, list[Any]]] = [
            (f"balance_{addr}_{bp}", [addr, bp])
            for addr in address_list
            for bp in block_params
        ]
        return await self.compare_over(inputs, total=len(inputs), unit="req")


class EthGetCodeRunner(BaseRunner):
    """Get contract code at various blocks.

    Uses ``null_as_empty_bytes`` normalizer because Ethrex returns ``null`` for
    EOAs while Geth returns ``"0x"`` — semantically the same empty bytecode.
    """

    method_name = "eth_getCode"
    description = "Get contract code at various blocks"
    extra_normalizers: ClassVar[list[Normalizer]] = [null_as_empty_bytes]

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Collecting contract addresses...")
        contracts: set[str] = set()
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
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

        contract_list = list(contracts)[:50]
        self.log(f"{self.method_name}: Testing {len(contract_list)} contracts")

        block_params = [hex(end_block), "latest"]
        inputs: list[tuple[str, list[Any]]] = [
            (f"code_{addr}_{bp}", [addr, bp])
            for addr in contract_list
            for bp in block_params
        ]
        return await self.compare_over(inputs, total=len(inputs), unit="req")


class EthGetStorageAtRunner(BaseRunner):
    """Get storage slot value at various blocks."""

    method_name = "eth_getStorageAt"
    description = "Get storage slot value at various blocks"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Collecting contract addresses...")
        contracts: set[str] = set()
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
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

        storage_slots = ["0x0", "0x1", "0x2"]
        inputs: list[tuple[str, list[Any]]] = []
        for addr in contract_list:
            for slot in storage_slots:
                padded_slot = "0x" + slot[2:].zfill(64)
                inputs.append(
                    (
                        f"storage_{addr}_slot_{slot}",
                        [addr, padded_slot, hex(end_block)],
                    )
                )
        return await self.compare_over(inputs, total=len(inputs), unit="req")


class EthGetProofRunner(BaseRunner):
    """Get Merkle proof for account and storage.

    Note: Erigon requires --prune.include-commitment-history=true.
    """

    method_name = "eth_getProof"
    description = "Get Merkle proof for account and storage"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Collecting addresses...")
        addresses: set[str] = set()
        contracts: set[str] = set()
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            for tx in block["transactions"]:
                if not isinstance(tx, dict):
                    continue
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

        address_list = list(addresses)[:20]
        contract_list = list(contracts)[:10]
        self.log(
            f"{self.method_name}: Testing {len(address_list)} EOAs, "
            f"{len(contract_list)} contracts"
        )

        storage_keys = ["0x" + "0" * 64, "0x" + "0" * 63 + "1"]
        inputs: list[tuple[str, list[Any]]] = []
        for addr in address_list:
            inputs.append((f"proof_eoa_{addr}", [addr, [], hex(end_block)]))
        for addr in contract_list:
            inputs.append(
                (f"proof_contract_{addr}", [addr, storage_keys, hex(end_block)])
            )
        return await self.compare_over(inputs, total=len(inputs), unit="req")


# =============================================================================
# Call methods
# =============================================================================


class EthCallRunner(BaseRunner):
    """Execute call with optional state/block overrides.

    Multi-variant runner: per tx, tests basic call and optionally a state-override
    variant. Calls `compare_one` directly for each variant.
    """

    method_name = "eth_call"
    description = "Execute call with optional state/block overrides"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        config = kwargs.get("eth_call_config", EthCallConfig())

        self.log(f"{self.method_name}: Collecting transactions to replay...")
        tx_list: list[tuple[int, str, dict[str, Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            for tx in block["transactions"]:
                if isinstance(tx, dict) and tx.get("to"):
                    call_obj = tx_to_call_obj(tx)
                    tx_hash = tx.get("hash", f"unknown_{block_num}")
                    tx_list.append((block_num, tx_hash, call_obj))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        tx_list = tx_list[:100]
        self.log(f"{self.method_name}: Testing {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0

        test_variants = 2 if config.test_state_override else 1
        total_tests = len(tx_list) * test_variants
        with tqdm(total=total_tests, desc=self.method_name, unit="call") as pbar:
            for block_num, tx_hash, call_obj in tx_list:
                state_block = hex(max(0, block_num - 1))

                # Variant 1: basic call
                tests_run += 1
                if await self.compare_one(
                    f"call_basic_{tx_hash}", [call_obj, state_block]
                ):
                    diff_count += 1
                pbar.update(1)

                # Variant 2: state override (modify sender balance)
                if config.test_state_override and call_obj.get("from"):
                    tests_run += 1
                    state_override = {
                        call_obj["from"]: {"balance": "0xFFFFFFFFFFFFFFFFFFFF"}
                    }
                    if await self.compare_one(
                        f"call_stateoverride_{tx_hash}",
                        [call_obj, state_block, state_override],
                    ):
                        diff_count += 1
                    pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthEstimateGasRunner(BaseRunner):
    """Estimate gas with optional state overrides.

    Multi-variant: basic, with block parameter, and with state override.
    `tx_to_call_obj` is called with `include_gas=False` because the gas field
    is what's being estimated — passing it would short-circuit the result.
    """

    method_name = "eth_estimateGas"
    description = "Estimate gas with optional state overrides"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Collecting transactions...")
        tx_list: list[tuple[int, str, dict[str, Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            for tx in block["transactions"]:
                if isinstance(tx, dict) and tx.get("to"):
                    call_obj = tx_to_call_obj(
                        tx,
                        include_gas=False,
                        include_gas_pricing=False,
                        include_access_list=False,
                    )
                    tx_hash = tx.get("hash", f"unknown_{block_num}")
                    tx_list.append((block_num, tx_hash, call_obj))

        if not tx_list:
            self.log(f"{self.method_name}: No transactions found")
            return RunnerResult(self.method_name, 0, 0)

        tx_list = tx_list[:100]
        self.log(f"{self.method_name}: Testing {len(tx_list)} transactions")

        tests_run = 0
        diff_count = 0

        total_tests = len(tx_list) * 3  # basic, with block, with state override
        with tqdm(total=total_tests, desc=self.method_name, unit="est") as pbar:
            for block_num, tx_hash, call_obj in tx_list:
                state_block = hex(max(0, block_num - 1))

                tests_run += 1
                if await self.compare_one(f"estimate_basic_{tx_hash}", [call_obj]):
                    diff_count += 1
                pbar.update(1)

                tests_run += 1
                if await self.compare_one(
                    f"estimate_block_{tx_hash}", [call_obj, state_block]
                ):
                    diff_count += 1
                pbar.update(1)

                tests_run += 1
                if call_obj.get("from"):
                    state_override = {
                        call_obj["from"]: {"balance": "0xFFFFFFFFFFFFFFFFFFFF"}
                    }
                    if await self.compare_one(
                        f"estimate_override_{tx_hash}",
                        [call_obj, state_block, state_override],
                    ):
                        diff_count += 1
                pbar.update(1)

        self.log(f"\n{self.method_name}: {tests_run} tests, {diff_count} diffs")
        return RunnerResult(self.method_name, tests_run, diff_count)


class EthCreateAccessListRunner(BaseRunner):
    """Generate access list for a transaction (EIP-2930).

    Uses ``tx_to_call_obj`` with gas pricing and access-list stripped — passing
    an existing access list would distort the result.
    """

    method_name = "eth_createAccessList"
    description = "Generate access list for transaction"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Collecting contract calls...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=True
            )
            if not block or not block.get("transactions"):
                continue
            state_block = hex(max(0, block_num - 1))
            for tx in block["transactions"]:
                if (
                    isinstance(tx, dict)
                    and tx.get("to")
                    and tx.get("input")
                    and tx["input"] != "0x"
                ):
                    call_obj = tx_to_call_obj(
                        tx, include_gas_pricing=False, include_access_list=False
                    )
                    tx_hash = tx.get("hash", f"unknown_{block_num}")
                    inputs.append((f"accesslist_{tx_hash}", [call_obj, state_block]))

        if not inputs:
            self.log(f"{self.method_name}: No contract calls found")
            return RunnerResult(self.method_name, 0, 0)

        inputs = inputs[:50]
        self.log(f"{self.method_name}: Testing {len(inputs)} calls")
        return await self.compare_over(inputs, total=len(inputs), unit="call")


# =============================================================================
# Fee methods
# =============================================================================


class EthGasPriceRunner(BaseRunner):
    """Get current gas price."""

    method_name = "eth_gasPrice"
    description = "Get current gas price"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        return await self.compare_over([("gas_price", [])], total=1, unit="req")


class EthMaxPriorityFeePerGasRunner(BaseRunner):
    """Get max priority fee suggestion."""

    method_name = "eth_maxPriorityFeePerGas"
    description = "Get max priority fee suggestion"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        return await self.compare_over([("max_priority_fee", [])], total=1, unit="req")


class EthFeeHistoryRunner(BaseRunner):
    """Get historical fee data with reward percentiles."""

    method_name = "eth_feeHistory"
    description = "Get historical fee data with reward percentiles"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        test_configs = [
            (10, [25.0, 50.0, 75.0]),
            (5, [10.0, 25.0, 50.0, 75.0, 90.0]),
            (10, []),
            (4, [0.0, 100.0]),
            (100, [50.0]),
        ]
        inputs: list[tuple[str, list[Any]]] = [
            (
                f"feehistory_{block_count}_{len(percentiles)}pct",
                [hex(block_count), "latest", percentiles],
            )
            for block_count, percentiles in test_configs
        ]
        return await self.compare_over(inputs, total=len(inputs), unit="req")


class EthBlobBaseFeeRunner(BaseRunner):
    """Get current blob base fee (post-Dencun)."""

    method_name = "eth_blobBaseFee"
    description = "Get current blob base fee (post-Dencun)"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        return await self.compare_over([("blob_base_fee", [])], total=1, unit="req")


# =============================================================================
# Log methods
# =============================================================================


class EthGetLogsRunner(BaseRunner):
    """Query logs with various filter options.

    Uses ``sort_logs_by_index`` normalizer — the spec does not mandate log
    ordering, so clients that return logs in different orders are both correct.
    """

    method_name = "eth_getLogs"
    description = "Query logs with various filter options"
    extra_normalizers: ClassVar[list[Normalizer]] = [sort_logs_by_index]

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
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

        test_cases: list[tuple[str, dict[str, Any]]] = [
            (
                "block_range",
                {"fromBlock": hex(start_block), "toBlock": hex(end_block)},
            ),
        ]

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
        test_cases.append(
            (
                "single_block",
                {"fromBlock": hex(end_block), "toBlock": hex(end_block)},
            )
        )

        self.log(f"{self.method_name}: Running {len(test_cases)} filter tests")
        inputs: list[tuple[str, list[Any]]] = [
            (f"logs_{name}", [filt]) for name, filt in test_cases
        ]
        return await self.compare_over(inputs, total=len(inputs), unit="filter")


# =============================================================================
# Chain info methods
# =============================================================================


class EthChainIdRunner(BaseRunner):
    """Get chain ID."""

    method_name = "eth_chainId"
    description = "Get chain ID"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        return await self.compare_over([("chain_id", [])], total=1, unit="req")


class EthBlockNumberRunner(BaseRunner):
    """Get latest block number."""

    method_name = "eth_blockNumber"
    description = "Get latest block number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        return await self.compare_over([("block_number", [])], total=1, unit="req")


class EthSyncingRunner(BaseRunner):
    """Get sync status."""

    method_name = "eth_syncing"
    description = "Get sync status"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        return await self.compare_over([("syncing", [])], total=1, unit="req")


# =============================================================================
# Uncle methods
# =============================================================================


class EthGetUncleCountByBlockHashRunner(BaseRunner):
    """Get uncle count by block hash."""

    method_name = "eth_getUncleCountByBlockHash"
    description = "Get uncle count by block hash"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if block and block.get("hash"):
                inputs.append((f"uncle_count_hash_{block_num}", [block["hash"]]))
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


class EthGetUncleCountByBlockNumberRunner(BaseRunner):
    """Get uncle count by block number."""

    method_name = "eth_getUncleCountByBlockNumber"
    description = "Get uncle count by block number"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        inputs = [
            (f"uncle_count_num_{n}", [hex(n)])
            for n in range(start_block, end_block + 1)
        ]
        return await self.compare_over(inputs, total=len(inputs), unit="blk")


class EthGetUncleByBlockHashAndIndexRunner(BaseRunner):
    """Get uncle by block hash and index."""

    method_name = "eth_getUncleByBlockHashAndIndex"
    description = "Get uncle by block hash and index"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Scanning for blocks with uncles...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if not block or not block.get("hash"):
                continue
            if block.get("uncles"):
                for uncle_idx in range(len(block["uncles"])):
                    inputs.append(
                        (
                            f"uncle_hash_{block_num}_{uncle_idx}",
                            [block["hash"], hex(uncle_idx)],
                        )
                    )

        # Fallback: verify error-handling on a block without uncles
        if not inputs:
            self.log(f"{self.method_name}: No uncles found in block range")
            block = await self.client.get_block(
                self.endpoints[0], start_block, full_transactions=False
            )
            if block and block.get("hash"):
                inputs.append(
                    (
                        f"uncle_hash_{start_block}_0",
                        [block["hash"], hex(0)],
                    )
                )

        return await self.compare_over(inputs, total=len(inputs), unit="req")


class EthGetUncleByBlockNumberAndIndexRunner(BaseRunner):
    """Get uncle by block number and index."""

    method_name = "eth_getUncleByBlockNumberAndIndex"
    description = "Get uncle by block number and index"

    async def run(
        self,
        start_block: int,
        end_block: int,
        **kwargs: Any,
    ) -> RunnerResult:
        self.log(f"{self.method_name}: Scanning for blocks with uncles...")
        inputs: list[tuple[str, list[Any]]] = []
        for block_num in range(start_block, end_block + 1):
            block = await self.client.get_block(
                self.endpoints[0], block_num, full_transactions=False
            )
            if block and block.get("uncles"):
                for uncle_idx in range(len(block["uncles"])):
                    inputs.append(
                        (
                            f"uncle_num_{block_num}_{uncle_idx}",
                            [hex(block_num), hex(uncle_idx)],
                        )
                    )

        if not inputs:
            self.log(f"{self.method_name}: No uncles found, testing index 0")
            inputs.append((f"uncle_num_{start_block}_0", [hex(start_block), hex(0)]))

        return await self.compare_over(inputs, total=len(inputs), unit="req")


# =============================================================================
# Runner registry
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
    """Run eth namespace method tests."""
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
