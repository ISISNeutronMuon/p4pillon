# Intro
This folder shows two different ways a developer may implement a custom `Rule`. 

## Custom Rule - Imatch
The imatch Rule is a simple rule that triggers an alarm of MAJOR severity when the value of an NTScalar PV matches a specified value. Although this rule can apply for any type, as the name suggests it makes most sense in the case of an integer. We do not specify what should happen in the case of an NTScalarArray.

## Implementations
### Public
The NTScalar is a Normative Type and its fields are defined by the specification of that type. However, in practice tools are permissive and will understand a type which is a superset of a Normative Type, ignoring those fields they do not expect or understand. As such it is possible to add additional fields to an NTScalar. 

In this case we add an `imatch` field which is a structure with a boolean `active` and an integer `imatch` field. If the `imatch` is active then the value of `imatch.imatch` is tested against the PV's value. If equal then a the severity is set to MAJOR otherwise it is cleared. 

The advantage of this method is that the imatch field is publicly available and may be manipulated through the standard EPICS pvAccess tools. This includes through the standard interfaces that are a part of p4p and p4pillon.

## Hidden 
An alternative way to implement the rule without modifying the Normative Type. The value of the imatch variable is held in the handler / Rule instead of the p4p.Value. This has the advantage that the Normative Type is unmodified. It has the possible disadvantage that the imatch value cannot be easily manipuluated by external pvAccess tools (hence describing it as hidden). As the code illustrates, it also makes it harder to reliably trigger the rule in some circumstances.

## Notes
This is a simplified example and does not consider some important cases. For example, what behaviour is correct in the case that the severity indicates invalidAlarm?